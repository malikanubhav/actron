"""GitHub connector (spec A, A8 and the event-driven part of A11).

`fetch_page(ws, step, cursor, page_token, config)` reads one HTTP page of one step and returns a
`Batch`; `write_batch(ws, step, batch)` writes it (idempotent upserts) and then adds the cross-source
links that need the code snapshot. The cursor is keyed per repository (the ingested repository and,
when set, the upstream); `_`-prefixed cursor keys are scratch values that live for one run.

Mapping functions are pure (JSON in, rows and links out) so contract tests can check them without
a server or a graph.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from actron.connectors import github_links as gl
from actron.connectors.common import (
    Batch,
    NotFoundError,
    RetryableProviderError,
    WriteResult,
    decode_token,
    dedupe_rows,
    encode_token,
    existing_ids,
    write_generic,
)
from actron.connectors.steps import SOURCE_STEPS
from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow, store_for
from actron.integrations.github_client import GithubClient, Page
from actron.logging import get_logger

log = get_logger(__name__)

STEPS: list[str] = SOURCE_STEPS["github"]
# Steps that also run for the upstream repository (A8 "Upstream history").
BOTH_REPOS = frozenset({"repo", "pulls", "pr_files", "pr_commits", "reviews", "review_comments",
                        "issues", "issue_comments", "check_runs"})
PR_STEPS = frozenset({"pr_files", "pr_commits", "reviews"})

PUBLIC_LIMIT_REASON = "public rate limit"
MAX_PAGES_PUBLIC = 2
MAX_PRS_PUBLIC = 5
MAX_PRS_CHECKS = 50
MAX_BRANCHES = 300
MAX_RUN_PAGES = 5


@dataclass
class Ctx:
    ws: str
    config: Mapping[str, Any]
    cursor: Mapping[str, Any]
    client: GithubClient
    repos: list[str]
    batch: Batch

    @property
    def authed(self) -> bool:
        return bool(self.config.get("token"))

    @property
    def per_page(self) -> int:
        return 100 if self.authed else 30

    @property
    def ingested(self) -> str:
        return self.repos[0]

    def repo_cur(self, repo: str) -> dict[str, Any]:
        value = self.cursor.get(repo, {})
        return dict(value) if isinstance(value, Mapping) else {}

    def since(self, repo: str, key: str) -> str:
        existing = self.repo_cur(repo).get(key)
        if existing:
            return str(existing)
        days = int(self.config.get("history_days") or 90)
        return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def update(self, repo: str, **values: Any) -> None:
        self.batch.cursor_update.setdefault(repo, {}).update(values)


def repos_of(config: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("repository", "upstream"):
        value = config.get(key)
        if value and str(value).lower() not in out:
            out.append(str(value).lower())
    return out


# Pure mapping
def _sha_like(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[0-9a-fA-F]{40}", value))


def user_ref(b: Batch, user: Mapping[str, Any] | None) -> str | None:
    if not user or not user.get("id"):
        return None
    uid = ids.github_user(user["id"])
    b.add_node("GithubUser", {
        "id": uid, "login": user.get("login") or str(user["id"]), "type": user.get("type"),
        "avatarUrl": user.get("avatar_url"), "url": user.get("html_url"), "sourceUrl": user.get("html_url"),
    })
    return uid


def repo_row(j: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": ids.github_repo(j["id"]), "fullName": j["full_name"], "name": j["name"],
        "owner": (j.get("owner") or {}).get("login") or j["full_name"].split("/")[0],
        "description": j.get("description"), "defaultBranch": j.get("default_branch"),
        "isPrivate": j.get("private"), "isFork": j.get("fork"), "language": j.get("language"),
        "topics": j.get("topics"), "stars": j.get("stargazers_count"), "url": j.get("html_url"),
        "sourceUrl": j.get("html_url"), "createdAt": j.get("created_at"), "pushedAt": j.get("pushed_at"),
    }


def map_repo(b: Batch, ingested: str, j: Mapping[str, Any], *, is_ingested: bool) -> dict[str, Any]:
    """Repository node, owner user, FORK_OF, HOSTED_AS. Returns the facts later steps need."""
    row = repo_row(j)
    b.add_node("GithubRepository", row)
    if is_ingested:
        b.add_link("HOSTED_AS", "CodeRepository", ids.code_repo(ingested), "GithubRepository", row["id"])
    parent = j.get("parent")
    if j.get("fork") and parent:
        prow = repo_row(parent)
        b.add_missing("GithubRepository", prow)
        b.add_link("FORK_OF", "GithubRepository", row["id"], "GithubRepository", prow["id"])
    return {"repo_id": j["id"], "default_branch": j.get("default_branch"),
            "owner_type": (j.get("owner") or {}).get("type"), "owner": (j.get("owner") or {}).get("login")}


def map_org(b: Batch, repo: str, repo_id: Any, j: Mapping[str, Any]) -> None:
    oid = ids.github_org(j["id"])
    b.add_node("GithubOrganization", {"id": oid, "login": j["login"], "name": j.get("name"),
                                      "description": j.get("description"), "url": j.get("html_url"),
                                      "sourceUrl": j.get("html_url")})
    b.add_link("BELONGS_TO_ORG", "GithubRepository", ids.github_repo(repo_id), "GithubOrganization", oid)


def _label_ref(b: Batch, repo: str, label: Mapping[str, Any]) -> str:
    lid = ids.github_label(repo, label["name"])
    b.add_node("GithubLabel", {"id": lid, "name": label["name"], "color": label.get("color")})
    return lid


def _milestone_ref(b: Batch, repo: str, m: Mapping[str, Any]) -> str:
    mid = ids.github_milestone(repo, m["number"])
    b.add_node("GithubMilestone", {"id": mid, "number": m["number"], "title": m.get("title") or str(m["number"]),
                                   "state": m.get("state")})
    return mid


def map_pull(b: Batch, repo: str, repo_id: Any, item: Mapping[str, Any],
             detail: Mapping[str, Any] | None) -> str:
    """One pull request with its users, labels, milestone and branches. `detail` is the single-PR JSON."""
    d = {**item, **(detail or {})}
    pid = ids.github_pr(repo, d["number"])
    merged = bool(d.get("merged")) or d.get("merged_at") is not None
    head, base = d.get("head") or {}, d.get("base") or {}
    b.add_node("GithubPullRequest", {
        "id": pid, "number": d["number"], "title": d.get("title") or "", "body": d.get("body"),
        "state": d.get("state"), "isDraft": d.get("draft"), "merged": merged, "mergedAt": d.get("merged_at"),
        "closedAt": d.get("closed_at"), "createdAt": d["created_at"], "updatedAt": d["updated_at"],
        "headRef": head.get("ref"), "headSha": head.get("sha"), "baseRef": base.get("ref"),
        "baseSha": base.get("sha"), "mergeCommitSha": d.get("merge_commit_sha"),
        "additions": d.get("additions"), "deletions": d.get("deletions"), "changedFiles": d.get("changed_files"),
        "url": d["html_url"], "sourceUrl": d["html_url"],
    })
    b.add_link("PR_IN_REPO", "GithubPullRequest", pid, "GithubRepository", ids.github_repo(repo_id))
    opener = user_ref(b, d.get("user"))
    if opener:
        b.add_link("OPENED_BY", "GithubPullRequest", pid, "GithubUser", opener)
    merger = user_ref(b, d.get("merged_by"))
    if merger:
        b.add_link("MERGED_BY", "GithubPullRequest", pid, "GithubUser", merger)
    for u in d.get("assignees") or []:
        uid = user_ref(b, u)
        if uid:
            b.add_link("PR_ASSIGNED_TO", "GithubPullRequest", pid, "GithubUser", uid)
    for u in d.get("requested_reviewers") or []:
        uid = user_ref(b, u)
        if uid:
            b.add_link("REVIEW_REQUESTED_FROM", "GithubPullRequest", pid, "GithubUser", uid)
    for label in d.get("labels") or []:
        b.add_link("PR_HAS_LABEL", "GithubPullRequest", pid, "GithubLabel", _label_ref(b, repo, label))
    if d.get("milestone"):
        b.add_link("PR_IN_MILESTONE", "GithubPullRequest", pid, "GithubMilestone",
                   _milestone_ref(b, repo, d["milestone"]))
    if head.get("ref"):
        head_repo = ((head.get("repo") or {}).get("full_name") or repo).lower()
        bid = ids.github_branch(head_repo, head["ref"])
        b.add_missing("GithubBranch", {"id": bid, "name": head["ref"]})
        b.add_link("FROM_BRANCH", "GithubPullRequest", pid, "GithubBranch", bid)
    if base.get("ref"):
        bid = ids.github_branch(repo, base["ref"])
        b.add_missing("GithubBranch", {"id": bid, "name": base["ref"]})
        b.add_link("INTO_BRANCH", "GithubPullRequest", pid, "GithubBranch", bid)
    return pid


def map_pr_files(b: Batch, repo: str, number: int, files: list[Mapping[str, Any]],
                 ingested: str) -> None:
    pid = ids.github_pr(repo, number)
    entries = b.extra.setdefault("files", [])
    for f in files:
        fid = ids.github_prfile(repo, number, f["filename"])
        hunks = gl.parse_patch_hunks(f.get("patch"))
        b.add_node("GithubPullRequestFile", {
            "id": fid, "path": f["filename"], "previousPath": f.get("previous_filename"),
            "status": f.get("status") or "modified", "additions": f.get("additions"),
            "deletions": f.get("deletions"), "hunks": gl.hunks_to_strings(hunks) or None,
        })
        b.add_link("CHANGES_FILE", "GithubPullRequest", pid, "GithubPullRequestFile", fid)
        entries.append({"prfile": fid, "pr": pid, "path": f["filename"], "status": f.get("status"),
                        "hunks": gl.hunks_to_strings(hunks)})
    b.extra["ingested_repo"] = ingested


def commit_row(repo: str, cj: Mapping[str, Any]) -> dict[str, Any]:
    c = cj.get("commit") or {}
    author = c.get("author") or {}
    committer = c.get("committer") or {}
    message = c.get("message") or ""
    parents = [p.get("sha") for p in cj.get("parents") or [] if p.get("sha")]
    sha = cj["sha"].lower()
    return {
        "id": ids.git_commit(repo, sha), "sha": sha, "shortSha": sha[:7],
        "subject": message.split("\n", 1)[0], "message": message, "authorName": author.get("name"),
        "authorEmail": (author.get("email") or "").lower() or None,
        "authoredAt": author.get("date") or committer.get("date") or "1970-01-01T00:00:00Z",
        "committedAt": committer.get("date"), "isMerge": len(parents) > 1,
        "parentShas": parents or None, "inClone": False,
    }


def map_pr_commits(b: Batch, repo: str, number: int, commits: list[Mapping[str, Any]], ingested: str) -> None:
    pid = ids.github_pr(repo, number)
    for cj in commits:
        row = commit_row(ingested, cj)
        b.add_missing("GitCommit", row)
        b.add_link("INCLUDES_COMMIT", "GithubPullRequest", pid, "GitCommit", row["id"])


def map_reviews(b: Batch, repo: str, number: int, reviews: list[Mapping[str, Any]]) -> None:
    pid = ids.github_pr(repo, number)
    for r in reviews:
        rid = ids.github_review(r["id"])
        b.add_node("GithubReview", {
            "id": rid, "state": r.get("state") or "COMMENTED", "body": r.get("body"),
            "commitSha": r.get("commit_id"), "submittedAt": r.get("submitted_at"), "url": r.get("html_url"),
            "sourceUrl": r.get("html_url"),
        })
        b.add_link("HAS_REVIEW", "GithubPullRequest", pid, "GithubReview", rid)
        uid = user_ref(b, r.get("user"))
        if uid:
            b.add_link("REVIEWED_BY", "GithubReview", rid, "GithubUser", uid)


def _pr_number_from_url(url: str | None) -> int | None:
    m = re.search(r"/(?:pulls|issues)/(\d+)$", url or "")
    return int(m.group(1)) if m else None


def map_review_comments(b: Batch, repo: str, comments: list[Mapping[str, Any]], ingested: str) -> None:
    entries = b.extra.setdefault("comments", [])
    for c in comments:
        number = _pr_number_from_url(c.get("pull_request_url"))
        cid = ids.github_review_comment(c["id"])
        b.add_node("GithubReviewComment", {
            "id": cid, "body": c.get("body") or "", "path": c.get("path") or "", "line": c.get("line"),
            "startLine": c.get("start_line"), "side": c.get("side"), "diffHunk": c.get("diff_hunk"),
            "commitSha": c.get("commit_id"), "createdAt": c["created_at"], "updatedAt": c.get("updated_at"),
            "url": c["html_url"], "sourceUrl": c["html_url"],
        })
        if number is not None:
            b.add_link("COMMENTS_ON_PR", "GithubReviewComment", cid, "GithubPullRequest",
                       ids.github_pr(repo, number))
            if c.get("path"):
                b.add_link("COMMENTS_ON_FILE", "GithubReviewComment", cid, "GithubPullRequestFile",
                           ids.github_prfile(repo, number, c["path"]))
        if c.get("pull_request_review_id"):
            b.add_link("PART_OF_REVIEW", "GithubReviewComment", cid, "GithubReview",
                       ids.github_review(c["pull_request_review_id"]))
        if c.get("in_reply_to_id"):
            b.add_link("REPLIES_TO", "GithubReviewComment", cid, "GithubReviewComment",
                       ids.github_review_comment(c["in_reply_to_id"]))
        uid = user_ref(b, c.get("user"))
        if uid:
            b.add_link("REVIEW_COMMENT_BY", "GithubReviewComment", cid, "GithubUser", uid)
        entries.append({"id": cid, "path": c.get("path"), "line": c.get("line") or c.get("original_line"),
                        "commit": c.get("commit_id"), "url": c.get("html_url"), "repo": repo})
    b.extra["ingested_repo"] = ingested


def map_issue(b: Batch, repo: str, repo_id: Any, j: Mapping[str, Any]) -> str:
    iid = ids.github_issue(repo, j["number"])
    b.add_node("GithubIssue", {
        "id": iid, "number": j["number"], "title": j.get("title") or "", "body": j.get("body"),
        "state": j.get("state"), "stateReason": j.get("state_reason"), "createdAt": j["created_at"],
        "updatedAt": j["updated_at"], "closedAt": j.get("closed_at"), "url": j["html_url"],
        "sourceUrl": j["html_url"],
    })
    b.add_link("ISSUE_IN_REPO", "GithubIssue", iid, "GithubRepository", ids.github_repo(repo_id))
    uid = user_ref(b, j.get("user"))
    if uid:
        b.add_link("ISSUE_OPENED_BY", "GithubIssue", iid, "GithubUser", uid)
    for u in j.get("assignees") or []:
        au = user_ref(b, u)
        if au:
            b.add_link("ISSUE_ASSIGNED_TO", "GithubIssue", iid, "GithubUser", au)
    for label in j.get("labels") or []:
        b.add_link("ISSUE_HAS_LABEL", "GithubIssue", iid, "GithubLabel", _label_ref(b, repo, label))
    if j.get("milestone"):
        b.add_link("ISSUE_IN_MILESTONE", "GithubIssue", iid, "GithubMilestone",
                   _milestone_ref(b, repo, j["milestone"]))
    return iid


def map_issue_comments(b: Batch, repo: str, comments: list[Mapping[str, Any]]) -> None:
    """Conversation comments. The issue and the PR share one number space, so only the link whose
    endpoint exists is created; the other is reported as missing and dropped."""
    for c in comments:
        number = _pr_number_from_url(c.get("issue_url"))
        cid = ids.github_issue_comment(c["id"])
        b.add_node("GithubIssueComment", {
            "id": cid, "body": c.get("body") or "", "createdAt": c["created_at"],
            "updatedAt": c.get("updated_at"), "url": c["html_url"], "sourceUrl": c["html_url"],
        })
        uid = user_ref(b, c.get("user"))
        if uid:
            b.add_link("COMMENT_BY", "GithubIssueComment", cid, "GithubUser", uid)
        if number is not None:
            b.add_link("ISSUE_DISCUSSED_IN", "GithubIssue", ids.github_issue(repo, number),
                       "GithubIssueComment", cid)
            b.add_link("PR_DISCUSSED_IN", "GithubPullRequest", ids.github_pr(repo, number),
                       "GithubIssueComment", cid)


# Fetching
def _no_more(ctx: Ctx, reason: str | None = None) -> Batch:
    if reason:
        ctx.batch.partial_reason = reason
    return ctx.batch


async def fetch_page(ws: str, step: str, cursor: Mapping[str, Any], page_token: str | None,
                     config: Mapping[str, Any]) -> Batch:
    if step not in STEPS:
        raise ValueError(f"unknown GitHub step {step!r}")
    repos = repos_of(config)
    if not repos:
        from actron.connectors.common import ValidationError

        raise ValidationError("no repository is configured for the GitHub connection")
    batch = Batch(step=step)
    client = GithubClient(config.get("token"), base_url=config.get("api_url"))
    ctx = Ctx(ws, config, cursor, client, repos, batch)
    tok = decode_token(page_token)
    handler = _HANDLERS[step]
    try:
        if not ctx.authed and ctx.repo_cur(ctx.ingested).get("_rate_stop") and step != "repo":
            batch.partial_reason = PUBLIC_LIMIT_REASON
            return batch
        try:
            await handler(ctx, tok)
        except RetryableProviderError as exc:
            if ctx.authed:
                raise
            # Unauthenticated: stop the run early instead of waiting an hour (A-AC-47).
            batch.next_page_token = None
            batch.partial_reason = PUBLIC_LIMIT_REASON
            batch.add_error(step, str(exc), exc.url)
            ctx.update(ctx.ingested, _rate_stop=True)
    finally:
        batch.meta["ratelimit_remaining"] = client.rate_remaining
        batch.meta["requests"] = client.requests_made
        await client.aclose()
    return batch


def _next_repo(ctx: Ctx, tok: dict[str, Any], step: str) -> str | None:
    """Token for the start of the next repository of a step, or None when this was the last."""
    pool = ctx.repos if step in BOTH_REPOS else ctx.repos[:1]
    r = int(tok.get("r", 0))
    return encode_token({"r": r + 1}) if r + 1 < len(pool) else None


def _repo_for(ctx: Ctx, tok: dict[str, Any]) -> tuple[str, int]:
    r = int(tok.get("r", 0))
    return ctx.repos[r], r


async def _listing(ctx: Ctx, tok: dict[str, Any], step: str, path: str, params: dict[str, Any],
                   *, etag_key: str | None = None, max_pages: int | None = None) -> tuple[str, Page | None]:
    """One page of a repository listing, with conditional requests on the first page."""
    repo, _ = _repo_for(ctx, tok)
    first = not tok.get("u")
    etags = ctx.repo_cur(repo).get("etags", {})
    key = etag_key or f"{step}"
    etag = etags.get(key) if first and etag_key else None
    page = await ctx.client.page(tok["u"] if tok.get("u") else path, None if tok.get("u") else params, etag)
    return repo, page


def _finish_listing(ctx: Ctx, tok: dict[str, Any], step: str, repo: str, page: Page,
                    etag_key: str | None = None, max_pages: int | None = None) -> None:
    """Set the next token; store the first page's ETag only when the whole listing finished."""
    n_pages = int(tok.get("n", 0)) + 1
    carried = dict(tok.get("e") or {})
    if etag_key and not tok.get("u") and page.etag:
        carried = {"k": etag_key, "v": page.etag}
    capped = max_pages is not None and n_pages >= max_pages
    if page.next_url and not capped:
        ctx.batch.next_page_token = encode_token({"r": tok.get("r", 0), "u": page.next_url, "n": n_pages,
                                                  "e": carried, "m": tok.get("m")})
        return
    if page.next_url and capped:
        ctx.batch.partial_reason = PUBLIC_LIMIT_REASON
    if carried:
        etags = dict(ctx.repo_cur(repo).get("etags", {}))
        etags[carried["k"]] = carried["v"]
        ctx.update(repo, etags=etags)
    ctx.batch.next_page_token = _next_repo(ctx, tok, step)


def _cap(ctx: Ctx) -> int | None:
    return None if ctx.authed else MAX_PAGES_PUBLIC


async def _step_repo(ctx: Ctx, tok: dict[str, Any]) -> None:
    repo, r = _repo_for(ctx, tok)
    page = await ctx.client.page(f"/repos/{repo}", None, ctx.repo_cur(repo).get("etags", {}).get("repo"))
    if r == 0:
        ctx.update(repo, _rate_stop=None)
    if page.status != 304 and isinstance(page.data, dict):
        facts = map_repo(ctx.batch, ctx.ingested, page.data, is_ingested=(r == 0))
        etags = dict(ctx.repo_cur(repo).get("etags", {}))
        if page.etag:
            etags["repo"] = page.etag
        ctx.update(repo, etags=etags, **facts)
    ctx.batch.next_page_token = _next_repo(ctx, tok, "repo")


async def _step_org(ctx: Ctx, tok: dict[str, Any]) -> None:
    repo = ctx.ingested
    cur = ctx.repo_cur(repo)
    if cur.get("owner_type") == "Organization" and cur.get("owner") and cur.get("repo_id"):
        page = await ctx.client.page(f"/orgs/{cur['owner']}", None, cur.get("etags", {}).get("org"))
        if page.status != 304 and isinstance(page.data, dict):
            map_org(ctx.batch, repo, cur["repo_id"], page.data)
            etags = dict(cur.get("etags", {}))
            if page.etag:
                etags["org"] = page.etag
            ctx.update(repo, etags=etags)


async def _step_contributors(ctx: Ctx, tok: dict[str, Any]) -> None:
    repo = ctx.ingested
    cur = ctx.repo_cur(repo)
    if tok.get("u"):
        page = await ctx.client.page(tok["u"])
    else:
        from actron.connectors.common import AuthError, ForbiddenError

        base = f"/repos/{repo}/"
        try:
            page = await ctx.client.page(base + (tok.get("p") or "collaborators"), {"per_page": ctx.per_page})
        # Collaborators need push access, and GitHub answers 401 to anonymous calls; contributors are public.
        # A bad token still fails below, because contributors raises AuthError too.
        except (AuthError, ForbiddenError, NotFoundError):
            if tok.get("p") == "contributors":
                raise
            page = await ctx.client.page(base + "contributors", {"per_page": ctx.per_page})
            tok = {**tok, "p": "contributors"}
    for u in page.data or []:
        uid = user_ref(ctx.batch, u)
        if uid and cur.get("repo_id"):
            ctx.batch.add_link("COLLABORATES_ON", "GithubUser", uid, "GithubRepository",
                               ids.github_repo(cur["repo_id"]))
    n = int(tok.get("n", 0)) + 1
    cap = _cap(ctx)
    if page.next_url and not (cap and n >= cap):
        ctx.batch.next_page_token = encode_token({"u": page.next_url, "n": n, "p": tok.get("p")})
    elif page.next_url:
        ctx.batch.partial_reason = PUBLIC_LIMIT_REASON


async def _step_pulls(ctx: Ctx, tok: dict[str, Any]) -> None:
    repo, r = _repo_for(ctx, tok)
    cur = ctx.repo_cur(repo)
    since = ctx.since(repo, "pulls_updated")
    has_cursor = bool(cur.get("pulls_updated"))
    params = {"state": "all", "sort": "updated", "direction": "desc", "per_page": ctx.per_page}
    first = not tok.get("u")
    etag = cur.get("etags", {}).get(f"pulls|{since}") if first else None
    page = await ctx.client.page(tok["u"] if tok.get("u") else f"/repos/{repo}/pulls",
                                 None if tok.get("u") else params, etag)
    if page.status == 304:
        ctx.batch.next_page_token = _next_repo(ctx, tok, "pulls")
        return
    items = [p for p in page.data or []]
    max_seen = tok.get("m") or since
    prs: dict[str, str] = {}
    reached_old = False
    repo_id = cur.get("repo_id")
    if repo_id is None:
        # `repo` ran earlier in the same run; the id is in its cursor update only after the save.
        repo_id = (await ctx.client.repository(repo))["id"]
        ctx.update(repo, repo_id=repo_id)
    for item in items:
        if item["updated_at"] < since or (has_cursor and item["updated_at"] <= since):
            reached_old = True
            break
        if not ctx.authed and len(prs) + int(tok.get("c", 0)) >= MAX_PRS_PUBLIC * 4:
            reached_old = True
            ctx.batch.partial_reason = PUBLIC_LIMIT_REASON
            break
        max_seen = max(max_seen, item["updated_at"])
        detail: Mapping[str, Any] | None = None
        try:
            detail = await ctx.client.get_json(f"/repos/{repo}/pulls/{item['number']}")
        except NotFoundError as exc:
            ctx.batch.add_error("pull_detail", f"pull request #{item['number']} not found", exc.url)
            ctx.batch.partial_reason = ctx.batch.partial_reason or f"pull request #{item['number']} not found"
        map_pull(ctx.batch, repo, repo_id, item, detail)
        prs[str(item["number"])] = (item.get("head") or {}).get("sha") or ""
    if prs:
        ctx.update(repo, _prs=prs)
    # merge commits: MERGED_AS needs a target, so create missing ones from the API (inClone=false)
    merged = [(p["id"], p["mergeCommitSha"]) for p in ctx.batch.nodes.get("GithubPullRequest", [])
              if p.get("merged") and _sha_like(p.get("mergeCommitSha"))
              and p["id"].startswith(f"github:pr:{repo}#")]
    if merged and r == 0:
        store = store_for(ctx.ws)
        import asyncio

        known = await asyncio.to_thread(
            existing_ids, store, "GitCommit", [ids.git_commit(ctx.ingested, sha) for _, sha in merged])
        for pid, sha in merged:
            cid = ids.git_commit(ctx.ingested, sha)
            if cid not in known and ctx.authed:
                try:
                    cj = await ctx.client.commit(repo, sha)
                    ctx.batch.add_missing("GitCommit", commit_row(ctx.ingested, cj))
                    known.add(cid)
                except NotFoundError:
                    pass
            if cid in known or cid in {r_["id"] for r_ in ctx.batch.only_if_missing.get("GitCommit", [])}:
                ctx.batch.add_link("MERGED_AS", "GithubPullRequest", pid, "GitCommit", cid)
    done = reached_old or not page.next_url
    n_pages = int(tok.get("n", 0)) + 1
    capped = not ctx.authed and n_pages >= MAX_PAGES_PUBLIC and not done
    carried = tok.get("e") or ({"k": f"pulls|{since}", "v": page.etag} if first and page.etag else None)
    if not done and not capped:
        ctx.batch.next_page_token = encode_token({"r": tok.get("r", 0), "u": page.next_url, "n": n_pages,
                                                  "m": max_seen, "e": carried})
        ctx.update(repo, _pulls_max=max_seen)
        return
    if capped:
        ctx.batch.partial_reason = PUBLIC_LIMIT_REASON
    update: dict[str, Any] = {"pulls_updated": max_seen}
    if carried and not capped:
        etags = dict(cur.get("etags", {}))
        etags[carried["k"]] = carried["v"]
        update["etags"] = etags
    ctx.update(repo, **update)
    ctx.batch.next_page_token = _next_repo(ctx, tok, "pulls")


def _pending_prs(ctx: Ctx, limit: int | None = None, newest_first: bool = False) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for repo in ctx.repos:
        for number, sha in (ctx.repo_cur(repo).get("_prs") or {}).items():
            out.append((repo, int(number), str(sha)))
    out.sort(key=lambda t: (t[0], t[1]), reverse=newest_first)
    if not ctx.authed:
        out = out[:MAX_PRS_PUBLIC]
    if limit:
        out = out[:limit]
    return out


async def _pr_children(ctx: Ctx, tok: dict[str, Any], step: str, tmpl: str,
                       handle: Callable[[Ctx, str, int, str, Any], None], *,
                       newest_first: bool = False, limit: int | None = None) -> None:
    prs = _pending_prs(ctx, limit, newest_first)
    i = int(tok.get("i", 0))
    if i >= len(prs):
        return
    repo, number, sha = prs[i]
    advance = True
    try:
        if tok.get("u"):
            page = await ctx.client.page(tok["u"])
        else:
            path = tmpl.format(repo=repo, n=number, sha=sha)
            page = await ctx.client.page(path, {"per_page": ctx.per_page} if "check-runs" not in tmpl else None)
        handle(ctx, repo, number, sha, page.data)
        if page.next_url and "check-runs" not in tmpl:
            ctx.batch.next_page_token = encode_token({"i": i, "u": page.next_url})
            advance = False
    except NotFoundError as exc:
        reason = f"pull request #{number} not found"
        ctx.batch.add_error(step, reason, exc.url)
        ctx.batch.partial_reason = ctx.batch.partial_reason or reason
    if advance:
        if i + 1 < len(prs):
            ctx.batch.next_page_token = encode_token({"i": i + 1})
        elif not ctx.authed and len(_pending_prs_all(ctx)) > len(prs):
            ctx.batch.partial_reason = PUBLIC_LIMIT_REASON


def _pending_prs_all(ctx: Ctx) -> list[str]:
    return [n for repo in ctx.repos for n in (ctx.repo_cur(repo).get("_prs") or {})]


async def _step_pr_files(ctx: Ctx, tok: dict[str, Any]) -> None:
    def handle(c: Ctx, repo: str, number: int, sha: str, data: Any) -> None:
        map_pr_files(c.batch, repo, number, data or [], c.ingested)

    await _pr_children(ctx, tok, "pr_files", "/repos/{repo}/pulls/{n}/files", handle)


async def _step_pr_commits(ctx: Ctx, tok: dict[str, Any]) -> None:
    def handle(c: Ctx, repo: str, number: int, sha: str, data: Any) -> None:
        map_pr_commits(c.batch, repo, number, data or [], c.ingested)

    await _pr_children(ctx, tok, "pr_commits", "/repos/{repo}/pulls/{n}/commits", handle)


async def _step_reviews(ctx: Ctx, tok: dict[str, Any]) -> None:
    def handle(c: Ctx, repo: str, number: int, sha: str, data: Any) -> None:
        map_reviews(c.batch, repo, number, data or [])

    await _pr_children(ctx, tok, "reviews", "/repos/{repo}/pulls/{n}/reviews", handle)


async def _step_review_comments(ctx: Ctx, tok: dict[str, Any]) -> None:
    repo, _ = _repo_for(ctx, tok)
    since = ctx.since(repo, "review_comments_since")
    params = {"sort": "updated", "direction": "asc", "since": since, "per_page": ctx.per_page}
    key = f"review_comments|{since}"
    _, page = await _listing(ctx, tok, "review_comments", f"/repos/{repo}/pulls/comments", params, etag_key=key)
    assert page is not None
    if page.status == 304:
        ctx.batch.next_page_token = _next_repo(ctx, tok, "review_comments")
        return
    items = page.data or []
    map_review_comments(ctx.batch, repo, items, ctx.ingested)
    if items:
        ctx.update(repo, review_comments_since=max(i["updated_at"] for i in items))
    _finish_listing(ctx, tok, "review_comments", repo, page, etag_key=key, max_pages=_cap(ctx))


async def _step_issues(ctx: Ctx, tok: dict[str, Any]) -> None:
    repo, _ = _repo_for(ctx, tok)
    since = ctx.since(repo, "issues_since")
    params = {"state": "all", "sort": "updated", "direction": "asc", "since": since, "per_page": ctx.per_page}
    key = f"issues|{since}"
    _, page = await _listing(ctx, tok, "issues", f"/repos/{repo}/issues", params, etag_key=key)
    assert page is not None
    if page.status == 304:
        ctx.batch.next_page_token = _next_repo(ctx, tok, "issues")
        return
    items = [i for i in page.data or [] if "pull_request" not in i]
    repo_id = ctx.repo_cur(repo).get("repo_id")
    if repo_id is None:
        repo_id = (await ctx.client.repository(repo))["id"]
    for j in items:
        map_issue(ctx.batch, repo, repo_id, j)
    if page.data:
        ctx.update(repo, issues_since=max(i["updated_at"] for i in page.data))
    _finish_listing(ctx, tok, "issues", repo, page, etag_key=key, max_pages=_cap(ctx))


async def _step_issue_comments(ctx: Ctx, tok: dict[str, Any]) -> None:
    repo, _ = _repo_for(ctx, tok)
    since = ctx.since(repo, "issue_comments_since")
    params = {"sort": "updated", "direction": "asc", "since": since, "per_page": ctx.per_page}
    key = f"issue_comments|{since}"
    _, page = await _listing(ctx, tok, "issue_comments", f"/repos/{repo}/issues/comments", params, etag_key=key)
    assert page is not None
    if page.status == 304:
        ctx.batch.next_page_token = _next_repo(ctx, tok, "issue_comments")
        return
    items = page.data or []
    map_issue_comments(ctx.batch, repo, items)
    if items:
        ctx.update(repo, issue_comments_since=max(i["updated_at"] for i in items))
    _finish_listing(ctx, tok, "issue_comments", repo, page, etag_key=key, max_pages=_cap(ctx))


async def _simple_list(ctx: Ctx, tok: dict[str, Any], step: str, path: str, params: dict[str, Any],
                       handle: Callable[[Ctx, str, Any], None], *, max_items: int | None = None) -> None:
    repo = ctx.ingested
    key = step
    etag = ctx.repo_cur(repo).get("etags", {}).get(key) if not tok.get("u") else None
    page = await ctx.client.page(tok["u"] if tok.get("u") else f"/repos/{repo}/{path}",
                                 None if tok.get("u") else params, etag)
    if page.status == 304:
        return
    handle(ctx, repo, page.data or [])
    n = int(tok.get("n", 0)) + 1
    total = int(tok.get("t", 0)) + len(page.data or [])
    carried = tok.get("e") or ({"k": key, "v": page.etag} if not tok.get("u") and page.etag else None)
    cap = _cap(ctx)
    more = bool(page.next_url) and not (cap and n >= cap) and not (max_items and total >= max_items)
    if more:
        ctx.batch.next_page_token = encode_token({"u": page.next_url, "n": n, "t": total, "e": carried})
        return
    if page.next_url and cap and n >= cap:
        ctx.batch.partial_reason = PUBLIC_LIMIT_REASON
    elif carried:
        etags = dict(ctx.repo_cur(repo).get("etags", {}))
        etags[carried["k"]] = carried["v"]
        ctx.update(repo, etags=etags)


def _repo_id(ctx: Ctx, repo: str) -> Any:
    return ctx.repo_cur(repo).get("repo_id")


async def _step_labels(ctx: Ctx, tok: dict[str, Any]) -> None:
    def handle(c: Ctx, repo: str, data: list[Mapping[str, Any]]) -> None:
        rid = _repo_id(c, repo)
        for label in data:
            lid = ids.github_label(repo, label["name"])
            c.batch.add_node("GithubLabel", {"id": lid, "name": label["name"], "color": label.get("color"),
                                             "description": label.get("description")})
            if rid:
                c.batch.add_link("LABEL_IN_REPO", "GithubLabel", lid, "GithubRepository", ids.github_repo(rid))

    await _simple_list(ctx, tok, "labels", "labels", {"per_page": ctx.per_page}, handle)


async def _step_milestones(ctx: Ctx, tok: dict[str, Any]) -> None:
    def handle(c: Ctx, repo: str, data: list[Mapping[str, Any]]) -> None:
        rid = _repo_id(c, repo)
        for m in data:
            mid = _milestone_ref(c.batch, repo, m)
            c.batch.nodes["GithubMilestone"][-1].update(
                {"description": m.get("description"), "dueOn": m.get("due_on")})
            if rid:
                c.batch.add_link("MILESTONE_IN_REPO", "GithubMilestone", mid, "GithubRepository",
                                 ids.github_repo(rid))

    await _simple_list(ctx, tok, "milestones", "milestones", {"state": "all", "per_page": ctx.per_page}, handle)


async def _step_releases(ctx: Ctx, tok: dict[str, Any]) -> None:
    def handle(c: Ctx, repo: str, data: list[Mapping[str, Any]]) -> None:
        rid = _repo_id(c, repo)
        for rel in data:
            rid_ = ids.github_release(rel["id"])
            c.batch.add_node("GithubRelease", {
                "id": rid_, "tagName": rel["tag_name"], "name": rel.get("name"), "body": rel.get("body"),
                "isDraft": rel.get("draft"), "isPrerelease": rel.get("prerelease"),
                "targetCommitish": rel.get("target_commitish"), "publishedAt": rel.get("published_at"),
                "url": rel.get("html_url"), "sourceUrl": rel.get("html_url"),
            })
            if rid:
                c.batch.add_link("RELEASE_IN_REPO", "GithubRelease", rid_, "GithubRepository", ids.github_repo(rid))
            uid = user_ref(c.batch, rel.get("author"))
            if uid:
                c.batch.add_link("RELEASED_BY", "GithubRelease", rid_, "GithubUser", uid)
            if _sha_like(rel.get("target_commitish")):
                c.batch.add_link("RELEASES_COMMIT", "GithubRelease", rid_, "GitCommit",
                                 ids.git_commit(c.ingested, rel["target_commitish"]))

    await _simple_list(ctx, tok, "releases", "releases", {"per_page": min(30, ctx.per_page)}, handle)


async def _step_branches(ctx: Ctx, tok: dict[str, Any]) -> None:
    def handle(c: Ctx, repo: str, data: list[Mapping[str, Any]]) -> None:
        rid = _repo_id(c, repo)
        default = c.repo_cur(repo).get("default_branch")
        for br in data:
            bid = ids.github_branch(repo, br["name"])
            sha = (br.get("commit") or {}).get("sha")
            c.batch.add_node("GithubBranch", {"id": bid, "name": br["name"], "headSha": sha,
                                              "isProtected": br.get("protected"),
                                              "isDefault": br["name"] == default if default else None})
            if rid:
                c.batch.add_link("BRANCH_IN_REPO", "GithubBranch", bid, "GithubRepository", ids.github_repo(rid))
            if sha and _sha_like(sha):
                c.batch.add_link("GITHUB_BRANCH_AT", "GithubBranch", bid, "GitCommit",
                                 ids.git_commit(c.ingested, sha))

    await _simple_list(ctx, tok, "branches", "branches", {"per_page": ctx.per_page}, handle,
                       max_items=MAX_BRANCHES)


async def _step_check_runs(ctx: Ctx, tok: dict[str, Any]) -> None:
    def handle(c: Ctx, repo: str, number: int, sha: str, data: Any) -> None:
        pid = ids.github_pr(repo, number)
        suites: dict[str, list[str]] = {}
        for run in (data or {}).get("check_runs", []):
            cid = ids.github_check(run["id"])
            c.batch.add_node("GithubCheckRun", {
                "id": cid, "name": run["name"], "status": run.get("status"), "conclusion": run.get("conclusion"),
                "headSha": run.get("head_sha") or sha, "startedAt": run.get("started_at"),
                "completedAt": run.get("completed_at"), "url": run.get("html_url"),
                "sourceUrl": run.get("html_url"),
            })
            c.batch.add_link("CHECK_FOR_PR", "GithubCheckRun", cid, "GithubPullRequest", pid)
            c.batch.add_link("CHECK_ON_COMMIT", "GithubCheckRun", cid, "GitCommit",
                             ids.git_commit(c.ingested, run.get("head_sha") or sha))
            suite = (run.get("check_suite") or {}).get("id")
            if suite is not None and repo == c.ingested:
                suites.setdefault(str(suite), []).append(cid)
        if suites:
            c.update(repo, _suites=suites)

    await _pr_children(ctx, tok, "check_runs", "/repos/{repo}/commits/{sha}/check-runs", handle,
                       newest_first=True, limit=MAX_PRS_CHECKS if ctx.authed else MAX_PRS_PUBLIC)
    if ctx.batch.next_page_token is None:
        for repo in ctx.repos:
            ctx.update(repo, _prs=None)


async def _step_workflow_runs(ctx: Ctx, tok: dict[str, Any]) -> None:
    repo = ctx.ingested
    cur = ctx.repo_cur(repo)
    since = ctx.since(repo, "runs_created")[:10]
    params = {"per_page": 50 if ctx.authed else 20, "created": f">={since}"}
    page = await ctx.client.page(tok["u"] if tok.get("u") else f"/repos/{repo}/actions/runs",
                                 None if tok.get("u") else params)
    suites = cur.get("_suites") or {}
    rid = cur.get("repo_id")
    newest = tok.get("m") or since
    for run in (page.data or {}).get("workflow_runs", []):
        wid = ids.github_run(run["id"])
        ctx.batch.add_node("GithubWorkflowRun", {
            "id": wid, "name": run.get("name") or "workflow", "event": run.get("event"),
            "status": run.get("status"), "conclusion": run.get("conclusion"), "headSha": run["head_sha"],
            "headBranch": run.get("head_branch"), "runNumber": run.get("run_number"),
            "createdAt": run.get("created_at"), "url": run.get("html_url"), "sourceUrl": run.get("html_url"),
        })
        newest = max(newest, (run.get("created_at") or "")[:10])
        if rid:
            ctx.batch.add_link("RUN_IN_REPO", "GithubWorkflowRun", wid, "GithubRepository", ids.github_repo(rid))
        for pr in run.get("pull_requests") or []:
            ctx.batch.add_link("RUN_FOR_PR", "GithubWorkflowRun", wid, "GithubPullRequest",
                               ids.github_pr(repo, pr["number"]))
        for check_id in suites.get(str(run.get("check_suite_id")), []):
            ctx.batch.add_link("CHECK_PART_OF_RUN", "GithubCheckRun", check_id, "GithubWorkflowRun", wid)
    n = int(tok.get("n", 0)) + 1
    cap = MAX_RUN_PAGES if ctx.authed else 1
    if page.next_url and n < cap:
        ctx.batch.next_page_token = encode_token({"u": page.next_url, "n": n, "m": newest})
        return
    if page.next_url:
        ctx.batch.partial_reason = None if ctx.authed else PUBLIC_LIMIT_REASON
    ctx.update(repo, runs_created=newest, _suites=None)


_HANDLERS: dict[str, Callable[[Ctx, dict[str, Any]], Any]] = {
    "repo": _step_repo, "org": _step_org, "contributors": _step_contributors, "pulls": _step_pulls,
    "pr_files": _step_pr_files, "pr_commits": _step_pr_commits, "reviews": _step_reviews,
    "review_comments": _step_review_comments, "issues": _step_issues, "issue_comments": _step_issue_comments,
    "labels": _step_labels, "milestones": _step_milestones, "releases": _step_releases,
    "branches": _step_branches, "check_runs": _step_check_runs, "workflow_runs": _step_workflow_runs,
}


# Writing
def write_batch(ws: str, step: str, batch: Batch) -> WriteResult:
    store = store_for(ws)
    result = write_generic(ws, batch, store=store)
    if batch.extra.get("files") or batch.extra.get("comments"):
        _cross_links(ws, store, batch, result)
    return result


def _cross_links(ws: str, store: GraphStore, batch: Batch, result: WriteResult) -> None:
    ingested = str(batch.extra.get("ingested_repo") or "")
    if not ingested:
        return
    snap = gl.Snapshot(store, ingested)
    clone = gl.clone_dir_for(ws, ingested)
    token = batch.extra.get("token") or (_connection_token(ws) if batch.extra.get("comments") else None)
    file_rows: list[LinkRow] = []
    touched_rows: list[LinkRow] = []
    touched_pairs: dict[tuple[str, str], int] = {}
    for f in batch.extra.get("files", []):
        rp = gl.resolve_current_path(snap, f["path"], clone)
        if rp.file_id:
            file_rows.append(LinkRow(f["prfile"], rp.file_id, {
                "method": "structural", "confidence": 0.7 if rp.renamed else 1.0}))
        if f.get("status") == "removed":
            continue
        for fn_id, lines in gl.functions_touched(snap, rp.path, gl.hunks_from_strings(f.get("hunks"))):
            key = (f["pr"], fn_id)
            touched_pairs[key] = touched_pairs.get(key, 0) + lines
    for (pr_id, fn_id), lines in touched_pairs.items():
        touched_rows.append(LinkRow(pr_id, fn_id, {"method": "structural", "confidence": gl.CONF_PR_TOUCHED,
                                                    "linesChanged": lines}))
    code_file_rows: list[LinkRow] = []
    fn_rows: list[LinkRow] = []
    for c in batch.extra.get("comments", []):
        if not c.get("path"):
            continue
        rp = gl.resolve_current_path(snap, c["path"], clone)
        if rp.file_id:
            code_file_rows.append(LinkRow(c["id"], rp.file_id, {
                "method": "structural", "confidence": gl.CONF_RENAMED if rp.renamed else gl.CONF_NO_RENAME}))
        link = gl.comment_function_link(snap, path=c["path"], line=c.get("line"), sha=c.get("commit"),
                                        clone=clone, token=token, resolved=rp)
        if link is None:
            continue
        if link.note:
            result.errors.append({"action": "comment_on_function", "error": link.note, "url": c.get("url"),
                                  "at": _now()})
        if link.fn_id:
            fn_rows.append(LinkRow(c["id"], link.fn_id, {"method": link.method, "confidence": link.confidence,
                                                         "sourceRef": c["id"]}))
    for rel, a, b, rows in (
        ("PR_FILE_IS", "GithubPullRequestFile", "CodeFile", file_rows),
        ("PR_TOUCHED", "GithubPullRequest", "CodeFunction", touched_rows),
        ("COMMENT_ON_CODE_FILE", "GithubReviewComment", "CodeFile", code_file_rows),
        ("COMMENT_ON_FUNCTION", "GithubReviewComment", "CodeFunction", fn_rows),
    ):
        if rows:
            res = store.upsert_links(rel, a, b, rows)
            result.links_created += res.created
            result.links_missing += len(res.missing)


def _connection_token(ws: str) -> str | None:
    """The token never travels in batches; the writer reads it from the connection when git needs it."""
    from actron.connectors.common import resolve_config

    try:
        token = resolve_config(ws, "github").values.get("token")
    except Exception as exc:  # no database in some unit tests; the fetch then stays anonymous
        log.warning("could not read the GitHub token for git fetch", extra={"error": str(exc)})
        return None
    return str(token) if token else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# Re-ingest one PR directly (merged PR from a webhook, or Actron's own PR after write-back)
async def ingest_pull(ws: str, config: Mapping[str, Any], repo: str, number: int) -> WriteResult:
    """Fetch one PR with files, commits, reviews and comments and write it now."""
    import asyncio

    repo = repo.lower()
    repos = repos_of(config)
    ingested = repos[0] if repos else repo
    client = GithubClient(config.get("token"), base_url=config.get("api_url"))
    total = WriteResult()
    try:
        repo_json = await client.repository(repo)
        detail = await client.get_json(f"/repos/{repo}/pulls/{number}")
        b = Batch(step="pulls")
        map_pull(b, repo, repo_json["id"], detail, detail)
        merge_sha = detail.get("merge_commit_sha")
        if detail.get("merged") and _sha_like(merge_sha):
            try:
                cj = await client.commit(repo, merge_sha)
                b.add_missing("GitCommit", commit_row(ingested, cj))
            except NotFoundError:
                pass
            b.add_link("MERGED_AS", "GithubPullRequest", ids.github_pr(repo, number), "GitCommit",
                       ids.git_commit(ingested, merge_sha))
        files = await _all_pages(client, f"/repos/{repo}/pulls/{number}/files")
        map_pr_files(b, repo, number, files, ingested)
        commits = await _all_pages(client, f"/repos/{repo}/pulls/{number}/commits")
        map_pr_commits(b, repo, number, commits, ingested)
        map_reviews(b, repo, number, await _all_pages(client, f"/repos/{repo}/pulls/{number}/reviews"))
        comments = await _all_pages(client, f"/repos/{repo}/pulls/{number}/comments")
        map_review_comments(b, repo, comments, ingested)
        map_issue_comments(b, repo, await _all_pages(client, f"/repos/{repo}/issues/{number}/comments"))
        b.extra["token"] = config.get("token")
        result = await asyncio.to_thread(write_batch, ws, "pulls", b)
        _absorb(total, result)
    finally:
        await client.aclose()
    return total


def _absorb(total: WriteResult, other: WriteResult) -> None:
    for k, v in other.counts.items():
        total.counts[k] = total.counts.get(k, 0) + v
    total.changed_ids.extend(other.changed_ids)
    total.links_created += other.links_created
    total.links_missing += other.links_missing
    total.errors.extend(other.errors)


async def _all_pages(client: GithubClient, path: str, cap: int = 10) -> list[Any]:
    out: list[Any] = []
    page = await client.page(path, {"per_page": 100})
    for _ in range(cap):
        out.extend(page.data or [])
        if not page.next_url:
            break
        page = await client.page(page.next_url)
    return out


# Merge watch (used by W6's RequestWorkflow)
@dataclass
class PrStatus:
    number: int
    state: str
    merged: bool
    closed: bool
    merge_commit_sha: str | None
    head_sha: str | None
    base_ref: str | None


async def check_pr_merged(repo: str, number: int, token: str | None, *, base_url: str | None = None) -> PrStatus:
    """One poll of a pull request: has it been merged or closed?"""
    async with GithubClient(token, base_url=base_url) as client:
        pr = await client.get_json(f"/repos/{repo}/pulls/{number}")
    merged = bool(pr.get("merged")) or pr.get("merged_at") is not None
    return PrStatus(number, pr.get("state", "open"), merged, pr.get("state") == "closed",
                    pr.get("merge_commit_sha"), (pr.get("head") or {}).get("sha"),
                    (pr.get("base") or {}).get("ref"))


# Webhooks (pure logic; W6 mounts POST /webhooks/github and runs the triggers)
@dataclass
class WebhookDecision:
    status: int
    reason: str
    event: str | None = None
    delivery_id: str | None = None
    triggers: list[str] = field(default_factory=list)
    debounced: list[str] = field(default_factory=list)
    reingest_pr: dict[str, Any] | None = None
    debounce_seconds: int = 30


def verify_signature(secret: str | None, body: bytes, header: str | None) -> bool:
    """HMAC-SHA256 over the raw body, compared in constant time. No secret means nothing verifies."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def sign_body(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def redis_dedupe(client: Any, ttl: int = 86400) -> Callable[[str], bool]:
    """`seen(delivery_id)` is True when the id was already recorded (Redis SET NX EX)."""
    def seen(delivery_id: str) -> bool:
        return not client.set(f"webhook:github:{delivery_id}", "1", nx=True, ex=ttl)

    return seen


def route_event(event: str, payload: Mapping[str, Any], working_branch: str | None) -> WebhookDecision:
    d = WebhookDecision(204, "ignored", event=event)
    if event == "ping":
        return WebhookDecision(200, "pong", event=event)
    if event == "push":
        if working_branch and payload.get("ref") == f"refs/heads/{working_branch}":
            d.status, d.reason, d.triggers = 202, "push to the working branch", ["code", "github"]
        else:
            d.reason = "push to another branch"
        return d
    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        action = payload.get("action")
        if action == "closed" and pr.get("merged"):
            base = (pr.get("base") or {}).get("ref")
            repo = (payload.get("repository") or {}).get("full_name")
            d.reingest_pr = {"repo": repo, "number": pr.get("number")}
            if working_branch and base == working_branch:
                d.status, d.reason, d.triggers = 202, "merged into the working branch", ["code", "github"]
            else:
                d.status, d.reason, d.triggers = 202, "merged into another branch", ["github"]
            return d
        if action in ("opened", "synchronize", "reopened", "closed", "edited", "ready_for_review"):
            d.status, d.reason, d.debounced = 202, f"pull request {action}", ["github"]
        return d
    if event in ("pull_request_review", "pull_request_review_comment", "issues", "issue_comment"):
        d.status, d.reason, d.debounced = 202, event.replace("_", " "), ["github"]
        return d
    return d


def handle_webhook(headers: Mapping[str, str], body: bytes, *, secret: str | None,
                   working_branch: str | None, repository: str | None = None,
                   seen: Callable[[str], bool] | None = None) -> WebhookDecision:
    """Verify, deduplicate and route one delivery. Nothing here touches Temporal; the caller runs the
    returned triggers (`schedule.trigger()` for each source, debounced ones after `debounce_seconds`)."""
    lower = {k.lower(): v for k, v in headers.items()}
    event = lower.get("x-github-event")
    delivery = lower.get("x-github-delivery")
    if not verify_signature(secret, body, lower.get("x-hub-signature-256")):
        return WebhookDecision(401, "bad or missing signature", event, delivery)
    if not event:
        return WebhookDecision(400, "missing event header", event, delivery)
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return WebhookDecision(400, "body is not JSON", event, delivery)
    if delivery and seen is not None and seen(delivery):
        return WebhookDecision(204, "duplicate delivery", event, delivery)
    if repository:
        full = ((payload.get("repository") or {}).get("full_name") or "").lower()
        if full and full != repository.lower() and event != "ping":
            return WebhookDecision(204, "other repository", event, delivery)
    decision = route_event(event, payload, working_branch)
    decision.delivery_id = delivery
    return decision


def dedupe_check(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Exposed for tests: one row per id."""
    return dedupe_rows(rows)
