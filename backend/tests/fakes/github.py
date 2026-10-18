"""A small fake GitHub REST server (ASGI) for contract and integration tests (spec A, A8).

Everything it serves is synthetic test data held in memory. It supports paging with Link headers,
ETags and 304, `since` filters, rate-limit and error injection, and records every request.

    fake = FakeGithub()
    fake.add_repo("acme/widgets", repo_id=100)
    transport = fake.transport()       # httpx.ASGITransport, in process
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

BASE = "http://fake.github"


@dataclass
class Injected:
    match: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    times: int = 1


def user(uid: int, login: str, kind: str = "User") -> dict[str, Any]:
    return {
        "id": uid, "login": login, "type": kind,
        "avatar_url": f"https://avatars.example/{uid}", "html_url": f"https://github.com/{login}",
    }


class FakeGithub:
    def __init__(self, *, require_token: bool = False) -> None:
        self.repos: dict[str, dict[str, Any]] = {}
        self.orgs: dict[str, dict[str, Any]] = {}
        self.collaborators: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.contributors: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.collaborators_forbidden: set[str] = set()
        # Real GitHub answers 401 to anonymous calls on /collaborators (seen live on 18 Oct 2026).
        self.collaborators_need_auth: set[str] = set()
        self.pulls: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
        self.pr_files: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(dict)
        self.pr_commits: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(dict)
        self.reviews: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(dict)
        self.review_comments: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.issues: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
        self.issue_comments: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.labels: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.milestones: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.releases: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.branches: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.check_runs: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
        self.runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.commits: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.deleted_pulls: dict[str, set[int]] = defaultdict(set)
        self.require_token = require_token
        self.delay = 0.0
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.injected: list[Injected] = []
        self.rate_remaining = 4999
        self.app = Starlette(routes=[Route("/{path:path}", self._dispatch, methods=["GET", "POST"])])

    # Setup helpers
    def transport(self) -> httpx.ASGITransport:
        return httpx.ASGITransport(app=self.app)

    def add_repo(self, full: str, *, repo_id: int, default_branch: str = "main", fork: bool = False,
                 parent: str | None = None, owner_type: str = "User", private: bool = False,
                 pushed: bool = True) -> dict[str, Any]:
        owner, name = full.split("/")
        data: dict[str, Any] = {
            "id": repo_id, "name": name, "full_name": full, "owner": user(repo_id * 10, owner, owner_type),
            "description": f"{full} (test fixture)", "default_branch": default_branch, "private": private,
            "fork": fork, "language": "Python", "topics": ["fixture"], "stargazers_count": 3,
            "html_url": f"https://github.com/{full}", "created_at": "2024-01-01T00:00:00Z",
            "pushed_at": "2026-01-01T00:00:00Z", "permissions": {"push": pushed, "pull": True},
        }
        if parent:
            data["parent"] = self.repos.get(parent) or {
                "id": repo_id + 1, "full_name": parent, "name": parent.split("/")[1],
                "owner": user(repo_id * 10 + 1, parent.split("/")[0]), "html_url": f"https://github.com/{parent}",
                "default_branch": "main", "private": False, "fork": False,
            }
        self.repos[full] = data
        if owner_type == "Organization":
            self.orgs[owner] = {"id": repo_id * 10, "login": owner, "name": owner.title(),
                                "description": "organisation fixture", "html_url": f"https://github.com/{owner}"}
        return data

    def add_pull(self, repo: str, number: int, *, title: str, author: dict[str, Any],
                 updated_at: str, created_at: str | None = None, state: str = "open", merged: bool = False,
                 head_ref: str = "feature", head_sha: str | None = None, base_ref: str = "main",
                 body: str = "", merge_commit_sha: str | None = None, labels: list[str] | None = None,
                 milestone: int | None = None, assignees: list[dict[str, Any]] | None = None,
                 merged_by: dict[str, Any] | None = None, requested: list[dict[str, Any]] | None = None,
                 additions: int = 10, deletions: int = 2, changed_files: int = 1) -> dict[str, Any]:
        head_sha = head_sha or hashlib.sha1(f"{repo}{number}".encode()).hexdigest()
        base = {
            "id": 5000 + number, "number": number, "title": title, "body": body, "state": state,
            "draft": False, "user": author, "created_at": created_at or updated_at, "updated_at": updated_at,
            "closed_at": updated_at if state == "closed" else None,
            "merged_at": updated_at if merged else None,
            "merge_commit_sha": merge_commit_sha,
            "head": {"ref": head_ref, "sha": head_sha, "repo": {"full_name": repo}},
            "base": {"ref": base_ref, "sha": "b" * 40, "repo": {"full_name": repo}},
            "html_url": f"https://github.com/{repo}/pull/{number}",
            "labels": [{"id": i + 1, "name": n, "color": "ededed"} for i, n in enumerate(labels or [])],
            "milestone": ({"number": milestone, "title": f"Milestone {milestone}", "state": "open"}
                          if milestone else None),
            "assignees": assignees or [], "requested_reviewers": requested or [],
        }
        self.pulls[repo][number] = base | {
            "merged_by": merged_by, "additions": additions, "deletions": deletions,
            "changed_files": changed_files, "merged": merged,
        }
        return base

    def touch_pull(self, repo: str, number: int, updated_at: str, **changes: Any) -> None:
        self.pulls[repo][number].update({"updated_at": updated_at, **changes})

    def inject(self, match: str, status: int, *, headers: dict[str, str] | None = None,
               body: Any = None, times: int = 1) -> None:
        self.injected.append(Injected(match, status, headers or {}, body, times))

    def count(self, pattern: str) -> int:
        return sum(1 for _, path, _ in self.requests if re.search(pattern, path))

    # Serving
    async def _dispatch(self, request: Request) -> Response:
        path = request.url.path
        query = dict(request.query_params)
        full_path = path + ("?" + request.url.query if request.url.query else "")
        self.requests.append((request.method, full_path, dict(request.headers)))
        if self.delay:
            await asyncio.sleep(self.delay)
        for inj in list(self.injected):
            if re.search(inj.match, path):
                inj.times -= 1
                if inj.times <= 0:
                    self.injected.remove(inj)
                return JSONResponse(inj.body or {"message": "injected"}, status_code=inj.status,
                                    headers=inj.headers)
        if self.require_token and not request.headers.get("authorization"):
            return JSONResponse({"message": "Requires authentication"}, status_code=401)
        data, extra_headers, status = self._route(path, query)
        headers = {"x-ratelimit-remaining": str(self.rate_remaining), "x-ratelimit-limit": "5000",
                   **extra_headers}
        if status != 200:
            return JSONResponse(data, status_code=status, headers=headers)
        if isinstance(data, tuple):  # (items, key) for paged lists
            items, _ = data
            body, link = self._page(items, query, request)
            if link:
                headers["link"] = link
        else:
            body = data
        etag = '"' + hashlib.md5(json.dumps(body, sort_keys=True).encode()).hexdigest() + '"'
        headers["etag"] = etag
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return JSONResponse(body, headers=headers)

    def _page(self, items: list[Any], query: dict[str, str], request: Request) -> tuple[Any, str | None]:
        per_page = min(int(query.get("per_page", 30)), 100)
        page = int(query.get("page", 1))
        chunk = items[(page - 1) * per_page : page * per_page]
        link = None
        if page * per_page < len(items):
            params = dict(request.query_params)
            params["page"] = str(page + 1)
            url = f"{BASE}{request.url.path}?" + "&".join(f"{k}={v}" for k, v in params.items())
            last = (len(items) + per_page - 1) // per_page
            lparams = dict(params, page=str(last))
            lurl = f"{BASE}{request.url.path}?" + "&".join(f"{k}={v}" for k, v in lparams.items())
            link = f'<{url}>; rel="next", <{lurl}>; rel="last"'
        return chunk, link

    def _route(self, path: str, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        routes: list[tuple[str, Callable[..., Any]]] = [
            (r"^/orgs/([^/]+)$", self._org),
            (r"^/repos/([^/]+/[^/]+)$", self._repo),
            (r"^/repos/([^/]+/[^/]+)/collaborators$", self._collab),
            (r"^/repos/([^/]+/[^/]+)/contributors$", self._contrib),
            (r"^/repos/([^/]+/[^/]+)/pulls$", self._pulls),
            (r"^/repos/([^/]+/[^/]+)/pulls/comments$", self._pr_comments),
            (r"^/repos/([^/]+/[^/]+)/pulls/(\d+)$", self._pull),
            (r"^/repos/([^/]+/[^/]+)/pulls/(\d+)/files$", self._files),
            (r"^/repos/([^/]+/[^/]+)/pulls/(\d+)/commits$", self._pcommits),
            (r"^/repos/([^/]+/[^/]+)/pulls/(\d+)/reviews$", self._reviews),
            (r"^/repos/([^/]+/[^/]+)/pulls/(\d+)/comments$", self._one_pr_comments),
            (r"^/repos/([^/]+/[^/]+)/issues/(\d+)/comments$", self._one_issue_comments),
            (r"^/repos/([^/]+/[^/]+)/issues$", self._issues),
            (r"^/repos/([^/]+/[^/]+)/issues/comments$", self._issue_comments),
            (r"^/repos/([^/]+/[^/]+)/labels$", self._labels),
            (r"^/repos/([^/]+/[^/]+)/milestones$", self._milestones),
            (r"^/repos/([^/]+/[^/]+)/releases$", self._releases),
            (r"^/repos/([^/]+/[^/]+)/branches$", self._branches),
            (r"^/repos/([^/]+/[^/]+)/commits/([0-9a-fA-F]+|[^/]+)/check-runs$", self._checks),
            (r"^/repos/([^/]+/[^/]+)/commits/([^/]+)$", self._commit),
            (r"^/repos/([^/]+/[^/]+)/actions/runs$", self._runs),
        ]
        for pattern, fn in routes:
            m = re.match(pattern, path)
            if m:
                return fn(*m.groups(), query=query)
        return {"message": "Not Found"}, {}, 404

    # Handlers
    def _org(self, org: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        if org in self.orgs:
            return self.orgs[org], {}, 200
        return {"message": "Not Found"}, {}, 404

    def _repo(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        if full in self.repos:
            return self.repos[full], {}, 200
        return {"message": "Not Found"}, {}, 404

    def _collab(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        if full in self.collaborators_forbidden:
            return {"message": "Must have push access to view repository collaborators."}, {}, 403
        if full in self.collaborators_need_auth:
            return {"message": "Requires authentication"}, {}, 401
        return (self.collaborators[full], "c"), {}, 200

    def _contrib(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        return (self.contributors[full], "c"), {}, 200

    def _pulls(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        items = [self._list_form(p) for p in self.pulls[full].values()]
        state = query.get("state", "open")
        if state != "all":
            items = [p for p in items if p["state"] == state]
        reverse = query.get("direction", "desc") == "desc"
        key = "updated_at" if query.get("sort") == "updated" else "created_at"
        items.sort(key=lambda p: p[key], reverse=reverse)
        return (items, "p"), {}, 200

    @staticmethod
    def _list_form(pr: dict[str, Any]) -> dict[str, Any]:
        skip = {"merged_by", "additions", "deletions", "changed_files", "merged"}
        return {k: v for k, v in pr.items() if k not in skip}

    def _pull(self, full: str, number: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        n = int(number)
        if n in self.deleted_pulls[full] or n not in self.pulls[full]:
            return {"message": "Not Found"}, {}, 404
        return self.pulls[full][n], {}, 200

    def _files(self, full: str, number: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        n = int(number)
        if n in self.deleted_pulls[full]:
            return {"message": "Not Found"}, {}, 404
        return (self.pr_files[full].get(n, []), "f"), {}, 200

    def _pcommits(self, full: str, number: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        n = int(number)
        if n in self.deleted_pulls[full]:
            return {"message": "Not Found"}, {}, 404
        return (self.pr_commits[full].get(n, []), "c"), {}, 200

    def _reviews(self, full: str, number: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        n = int(number)
        if n in self.deleted_pulls[full]:
            return {"message": "Not Found"}, {}, 404
        return (self.reviews[full].get(n, []), "r"), {}, 200

    def _one_pr_comments(self, full: str, number: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        items = [c for c in self.review_comments[full] if c["pull_request_url"].endswith(f"/pulls/{number}")]
        return (items, "c"), {}, 200

    def _one_issue_comments(self, full: str, number: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        items = [c for c in self.issue_comments[full] if c["issue_url"].endswith(f"/issues/{number}")]
        return (items, "c"), {}, 200

    def _since(self, items: list[dict[str, Any]], query: dict[str, str]) -> list[dict[str, Any]]:
        since = query.get("since")
        out = [i for i in items if not since or i["updated_at"] > since]
        out.sort(key=lambda i: i["updated_at"], reverse=query.get("direction", "asc") == "desc")
        return out

    def _pr_comments(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        return (self._since(self.review_comments[full], query), "rc"), {}, 200

    def _issues(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        items = list(self.issues[full].values())
        for n, pr in self.pulls[full].items():  # GitHub lists pull requests among issues
            items.append({"number": n, "title": pr["title"], "updated_at": pr["updated_at"],
                          "created_at": pr["created_at"], "state": pr["state"], "pull_request": {"url": "x"},
                          "id": 9000 + n, "html_url": pr["html_url"].replace("/pull/", "/issues/")})
        state = query.get("state", "open")
        if state != "all":
            items = [i for i in items if i["state"] == state]
        since = query.get("since")
        items = [i for i in items if not since or i["updated_at"] > since]
        sort_key = "updated_at" if query.get("sort") == "updated" else "created_at"
        items.sort(key=lambda i: i[sort_key], reverse=query.get("direction", "desc") == "desc")
        return (items, "i"), {}, 200

    def _issue_comments(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        return (self._since(self.issue_comments[full], query), "ic"), {}, 200

    def _labels(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        return (self.labels[full], "l"), {}, 200

    def _milestones(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        return (self.milestones[full], "m"), {}, 200

    def _releases(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        return (self.releases[full], "rel"), {}, 200

    def _branches(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        return (self.branches[full], "b"), {}, 200

    def _checks(self, full: str, sha: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        runs = self.check_runs[full].get(sha, [])
        return {"total_count": len(runs), "check_runs": runs}, {}, 200

    def _commit(self, full: str, sha: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        if sha in self.commits[full]:
            return self.commits[full][sha], {}, 200
        return {"message": "Not Found"}, {}, 404

    def _runs(self, full: str, *, query: dict[str, str]) -> tuple[Any, dict[str, str], int]:
        runs = list(self.runs[full])
        created = query.get("created", "")
        if created.startswith(">="):
            runs = [r for r in runs if r["created_at"][:10] >= created[2:12]]
        per = min(int(query.get("per_page", 30)), 100)
        page = int(query.get("page", 1))
        chunk = runs[(page - 1) * per : page * per]
        extra: dict[str, str] = {}
        if page * per < len(runs):
            extra["link"] = f'<{BASE}/repos/x/actions/runs?per_page={per}&page={page + 1}>; rel="next"'
        return {"total_count": len(runs), "workflow_runs": chunk}, extra, 200


# Builders for fixture data
def commit_json(sha: str, message: str, author: str, email: str, date: str) -> dict[str, Any]:
    return {
        "sha": sha, "commit": {"message": message, "author": {"name": author, "email": email, "date": date},
                               "committer": {"name": author, "email": email, "date": date}},
        "author": None, "parents": [],
    }


def review_comment_json(cid: int, pr_number: int, repo: str, *, path: str, line: int, body: str,
                        author: dict[str, Any], commit_id: str, created: str, updated: str | None = None,
                        review_id: int | None = None, reply_to: int | None = None) -> dict[str, Any]:
    return {
        "id": cid, "pull_request_review_id": review_id, "in_reply_to_id": reply_to, "body": body,
        "path": path, "line": line, "start_line": None, "side": "RIGHT", "diff_hunk": "@@ -1,3 +1,4 @@",
        "commit_id": commit_id, "created_at": created, "updated_at": updated or created, "user": author,
        "html_url": f"https://github.com/{repo}/pull/{pr_number}#discussion_r{cid}",
        "pull_request_url": f"{BASE}/repos/{repo}/pulls/{pr_number}",
    }


def issue_comment_json(cid: int, repo: str, number: int, *, body: str, author: dict[str, Any],
                       created: str, updated: str | None = None) -> dict[str, Any]:
    return {
        "id": cid, "body": body, "user": author, "created_at": created, "updated_at": updated or created,
        "html_url": f"https://github.com/{repo}/issues/{number}#issuecomment-{cid}",
        "issue_url": f"{BASE}/repos/{repo}/issues/{number}",
    }


def build_pr_fixture(fake: FakeGithub, repo: str = "acme/widgets", *, number: int = 7,
                     head_sha: str = "a1" * 20, commit_id: str | None = None) -> dict[str, Any]:
    """The A-AC-45 fixture: one PR with 2 files, 2 commits, 2 reviews, 5 review comments (one reply chain)
    and 2 conversation comments. Returns the ids the tests assert on."""
    alice, bob = user(11, "alice"), user(12, "bob")
    fake.add_repo(repo, repo_id=100)
    fake.add_pull(repo, number, title="Add retry to sync", author=alice, updated_at="2026-03-02T10:00:00Z",
                  created_at="2026-03-01T09:00:00Z", state="closed", merged=True, head_sha=head_sha,
                  head_ref="retry-sync", body="Fixes #3. See ENG-12.", merge_commit_sha="c" * 40,
                  labels=["bug"], milestone=2, assignees=[bob], merged_by=bob, requested=[bob],
                  additions=12, deletions=3, changed_files=2)
    fake.pr_files[repo][number] = [
        {"filename": "src/sync.py", "status": "modified", "additions": 8, "deletions": 2,
         "patch": "@@ -10,3 +10,5 @@ def run\n a\n+b\n+c\n d\n@@ -40,2 +42,4 @@ def other\n x\n+y\n+z\n w"},
        {"filename": "src/new_name.py", "previous_filename": "src/old_name.py", "status": "renamed",
         "additions": 4, "deletions": 1, "patch": "@@ -1,2 +1,3 @@\n a\n+b\n c"},
    ]
    fake.pr_commits[repo][number] = [
        commit_json("d" * 40, "Add retry\n\nbody", "Alice", "alice@example.com", "2026-03-01T09:30:00Z"),
        commit_json("e" * 40, "Tidy", "Alice", "alice@example.com", "2026-03-01T09:45:00Z"),
    ]
    fake.reviews[repo][number] = [
        {"id": 301, "state": "COMMENTED", "body": "A few notes", "commit_id": head_sha,
         "submitted_at": "2026-03-01T12:00:00Z", "user": bob,
         "html_url": f"https://github.com/{repo}/pull/{number}#pullrequestreview-301"},
        {"id": 302, "state": "APPROVED", "body": "Looks good", "commit_id": head_sha,
         "submitted_at": "2026-03-02T09:00:00Z", "user": bob,
         "html_url": f"https://github.com/{repo}/pull/{number}#pullrequestreview-302"},
    ]
    cid = commit_id or head_sha
    fake.review_comments[repo] = [
        review_comment_json(401, number, repo, path="src/sync.py", line=11, body="Why retry here?",
                            author=bob, commit_id=cid, created="2026-03-01T12:01:00Z", review_id=301),
        review_comment_json(402, number, repo, path="src/sync.py", line=11, body="Because the API flakes.",
                            author=alice, commit_id=cid, created="2026-03-01T12:30:00Z", review_id=301,
                            reply_to=401),
        review_comment_json(403, number, repo, path="src/sync.py", line=43, body="Add a test for this.",
                            author=bob, commit_id=cid, created="2026-03-01T12:02:00Z", review_id=301),
        review_comment_json(404, number, repo, path="src/new_name.py", line=2, body="Nit: rename.",
                            author=bob, commit_id=cid, created="2026-03-01T12:03:00Z", review_id=301),
        review_comment_json(405, number, repo, path="src/sync.py", line=11, body="Ok, approved.",
                            author=bob, commit_id=cid, created="2026-03-02T08:00:00Z", review_id=302,
                            reply_to=402),
    ]
    fake.issue_comments[repo] = [
        issue_comment_json(501, repo, number, body="Ready to merge?", author=bob,
                           created="2026-03-02T09:30:00Z"),
        issue_comment_json(502, repo, number, body="Merging now.", author=alice,
                           created="2026-03-02T09:45:00Z"),
    ]
    fake.issues[repo][3] = {
        "id": 8003, "number": 3, "title": "Sync fails on rate limit", "body": "It crashes.", "state": "closed",
        "state_reason": "completed", "user": alice, "created_at": "2026-02-20T00:00:00Z",
        "updated_at": "2026-03-02T10:00:00Z", "closed_at": "2026-03-02T10:00:00Z",
        "html_url": f"https://github.com/{repo}/issues/3", "labels": [{"id": 1, "name": "bug", "color": "d73a4a"}],
        "milestone": {"number": 2, "title": "Milestone 2", "state": "open"}, "assignees": [bob],
    }
    fake.labels[repo] = [{"id": 1, "name": "bug", "color": "d73a4a", "description": "Something broke"}]
    fake.milestones[repo] = [{"number": 2, "title": "Milestone 2", "description": "", "state": "open",
                              "due_on": None}]
    fake.branches[repo] = [
        {"name": "main", "commit": {"sha": "f" * 40}, "protected": True},
        {"name": "retry-sync", "commit": {"sha": head_sha}, "protected": False},
    ]
    fake.releases[repo] = [{"id": 601, "tag_name": "v1.0", "name": "One", "body": "first", "draft": False,
                            "prerelease": False, "target_commitish": "main",
                            "published_at": "2026-03-03T00:00:00Z", "author": alice,
                            "html_url": f"https://github.com/{repo}/releases/tag/v1.0"}]
    fake.collaborators[repo] = [alice, bob]
    fake.check_runs[repo][head_sha] = [
        {"id": 701, "name": "tests", "status": "completed", "conclusion": "success", "head_sha": head_sha,
         "started_at": "2026-03-01T09:50:00Z", "completed_at": "2026-03-01T09:55:00Z",
         "html_url": "https://github.com/x/runs/701", "check_suite": {"id": 801}}]
    fake.runs[repo] = [{"id": 801, "name": "CI", "event": "pull_request", "status": "completed",
                        "conclusion": "success", "head_sha": head_sha, "head_branch": "retry-sync",
                        "run_number": 5, "created_at": "2026-03-01T09:49:00Z", "check_suite_id": 801,
                        "html_url": "https://github.com/x/actions/runs/801",
                        "pull_requests": [{"number": number}]}]
    return {"repo": repo, "number": number, "head_sha": head_sha}
