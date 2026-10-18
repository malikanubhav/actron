"""Stable id builders for every node type (spec A, A.C3) and a parser back to parts.

Rules: repo names (`owner/name`) are lowercased; paths and qualified names keep case;
the `~n` duplicate suffix is added only for n >= 2.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

# Label for each id prefix. Order matters only for readability; lookups are exact.
PREFIX_LABELS: dict[str, str] = {
    "code:repo": "CodeRepository",
    "code:component": "CodeComponent",
    "code:dep": "CodeDependency",
    "code:file": "CodeFile",
    "code:class": "CodeClass",
    "code:fn": "CodeFunction",
    "code:chunk": "CodeChunk",
    "code:doc": "CodeDocument",
    "code:owners": "CodeOwnerRule",
    "git:commit": "GitCommit",
    "git:author": "GitAuthor",
    "git:branch": "GitBranch",
    "git:tag": "GitTag",
    "git:change": "GitFileChange",
    "github:repo": "GithubRepository",
    "github:org": "GithubOrganization",
    "github:user": "GithubUser",
    "github:pr": "GithubPullRequest",
    "github:prfile": "GithubPullRequestFile",
    "github:review": "GithubReview",
    "github:reviewcomment": "GithubReviewComment",
    "github:issue": "GithubIssue",
    "github:issuecomment": "GithubIssueComment",
    "github:label": "GithubLabel",
    "github:milestone": "GithubMilestone",
    "github:release": "GithubRelease",
    "github:branch": "GithubBranch",
    "github:run": "GithubWorkflowRun",
    "github:check": "GithubCheckRun",
    "slack:workspace": "SlackWorkspace",
    "slack:channel": "SlackChannel",
    "slack:user": "SlackUser",
    "slack:msg": "SlackMessage",
    "slack:usergroup": "SlackUserGroup",
    "slack:file": "SlackFile",
    "slack:reaction": "SlackReaction",
    "linear:team": "LinearTeam",
    "linear:user": "LinearUser",
    "linear:issue": "LinearIssue",
    "linear:comment": "LinearComment",
    "linear:state": "LinearState",
    "linear:label": "LinearLabel",
    "linear:project": "LinearProject",
    "actron:workspace": "Workspace",
    "actron:person": "Person",
    "actron:identity": "Identity",
    "actron:team": "Team",
    "actron:ref": "Reference",
    "actron:feature": "Feature",
    "actron:decision": "Decision",
    "actron:procedure": "Procedure",
    "actron:request": "Request",
    "actron:investigation": "Investigation",
    "actron:build": "BuildRun",
}

_NAMESPACE = uuid.UUID("5f0c7c0e-3a5e-4c1b-9d0a-6b1f2a4c8e11")


class InvalidId(ValueError):
    """Raised when a string is not a known Actron id."""


@dataclass(frozen=True)
class ParsedId:
    prefix: str
    label: str
    parts: dict[str, str] = field(default_factory=dict)


def _repo(repo: str) -> str:
    repo = repo.strip().strip("/")
    if repo.count("/") != 1 or not all(repo.split("/")):
        raise InvalidId(f"repository must be owner/name, got {repo!r}")
    return repo.lower()


def _dup(name: str, dup: int) -> str:
    if dup < 1:
        raise InvalidId("duplicate index starts at 1")
    return name if dup == 1 else f"{name}~{dup}"


def slugify(text: str) -> str:
    """Lowercase, non-alphanumerics to `-`, collapsed and trimmed (A.C3)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "\x1f".join(parts)))


# Code and git
def code_repo(repo: str) -> str:
    return f"code:repo:{_repo(repo)}"


def code_component(repo: str, path: str) -> str:
    return f"code:component:{_repo(repo)}:{path or '.'}"


def code_dep(ecosystem: str, name: str) -> str:
    return f"code:dep:{ecosystem.lower()}:{name.lower()}"


def code_file(repo: str, path: str) -> str:
    return f"code:file:{_repo(repo)}:{path}"


def code_class(repo: str, path: str, qualname: str, dup: int = 1) -> str:
    return f"code:class:{_repo(repo)}:{path}::{_dup(qualname, dup)}"


def code_fn(repo: str, path: str, qualname: str, dup: int = 1) -> str:
    return f"code:fn:{_repo(repo)}:{path}::{_dup(qualname, dup)}"


def code_chunk(repo: str, path: str, start: int, end: int) -> str:
    return f"code:chunk:{_repo(repo)}:{path}#L{start}-L{end}"


def code_doc(repo: str, path: str, slug: str, dup: int = 1) -> str:
    return f"code:doc:{_repo(repo)}:{path}#{_dup(slug, dup)}"


def code_owners(repo: str, line: int) -> str:
    return f"code:owners:{_repo(repo)}:{line}"


def git_commit(repo: str, sha: str) -> str:
    return f"git:commit:{_repo(repo)}:{sha.lower()}"


def git_author(email: str) -> str:
    return f"git:author:{email.strip().lower()}"


def git_branch(repo: str, name: str) -> str:
    return f"git:branch:{_repo(repo)}:{name}"


def git_tag(repo: str, name: str) -> str:
    return f"git:tag:{_repo(repo)}:{name}"


def git_change(repo: str, sha: str, path: str) -> str:
    return f"git:change:{_repo(repo)}:{sha.lower()}:{path}"


# GitHub
def github_repo(numeric_id: int | str) -> str:
    return f"github:repo:{numeric_id}"


def github_org(numeric_id: int | str) -> str:
    return f"github:org:{numeric_id}"


def github_user(numeric_id: int | str) -> str:
    return f"github:user:{numeric_id}"


def github_pr(repo: str, number: int) -> str:
    return f"github:pr:{_repo(repo)}#{number}"


def github_prfile(repo: str, number: int, path: str) -> str:
    return f"github:prfile:{_repo(repo)}#{number}:{path}"


def github_review(numeric_id: int | str) -> str:
    return f"github:review:{numeric_id}"


def github_review_comment(numeric_id: int | str) -> str:
    return f"github:reviewcomment:{numeric_id}"


def github_issue(repo: str, number: int) -> str:
    return f"github:issue:{_repo(repo)}#{number}"


def github_issue_comment(numeric_id: int | str) -> str:
    return f"github:issuecomment:{numeric_id}"


def github_label(repo: str, name: str) -> str:
    return f"github:label:{_repo(repo)}:{name}"


def github_milestone(repo: str, number: int) -> str:
    return f"github:milestone:{_repo(repo)}#{number}"


def github_release(numeric_id: int | str) -> str:
    return f"github:release:{numeric_id}"


def github_branch(repo: str, name: str) -> str:
    return f"github:branch:{_repo(repo)}:{name}"


def github_run(numeric_id: int | str) -> str:
    return f"github:run:{numeric_id}"


def github_check(numeric_id: int | str) -> str:
    return f"github:check:{numeric_id}"


# Slack
def slack_workspace(team_id: str) -> str:
    return f"slack:workspace:{team_id}"


def slack_channel(channel_id: str) -> str:
    return f"slack:channel:{channel_id}"


def slack_user(user_id: str) -> str:
    return f"slack:user:{user_id}"


def slack_msg(channel_id: str, ts: str, version: int | None = None) -> str:
    base = f"slack:msg:{channel_id}:{ts}"
    return base if version is None else f"{base}@v{version}"


def slack_usergroup(group_id: str) -> str:
    return f"slack:usergroup:{group_id}"


def slack_file(file_id: str) -> str:
    return f"slack:file:{file_id}"


def slack_reaction(channel_id: str, ts: str, name: str) -> str:
    return f"slack:reaction:{channel_id}:{ts}:{name}"


# Linear
def linear_team(uid: str) -> str:
    return f"linear:team:{uid}"


def linear_user(uid: str) -> str:
    return f"linear:user:{uid}"


def linear_issue(uid: str, version: int | None = None) -> str:
    return f"linear:issue:{uid}" if version is None else f"linear:issue:{uid}@v{version}"


def linear_comment(uid: str, version: int | None = None) -> str:
    return f"linear:comment:{uid}" if version is None else f"linear:comment:{uid}@v{version}"


def linear_state(uid: str) -> str:
    return f"linear:state:{uid}"


def linear_label(uid: str) -> str:
    return f"linear:label:{uid}"


def linear_project(uid: str) -> str:
    return f"linear:project:{uid}"


# Core
def workspace(ws: str) -> str:
    return f"actron:workspace:{ws}"


def person(ws: str, primary_key: str) -> str:
    return f"actron:person:{stable_uuid(ws, primary_key)}"


def identity(provider: str, account_id: str) -> str:
    return f"actron:identity:{provider}:{account_id}"


def reference(kind: str, key: str) -> str:
    return f"actron:ref:{kind}:{key}"


def feature(slug: str) -> str:
    return f"actron:feature:{slugify(slug)}"


def decision(*source_parts: str) -> str:
    return f"actron:decision:{stable_uuid(*source_parts)}"


def procedure(area: str) -> str:
    return f"actron:procedure:{slugify(area)}"


def request(request_id: str) -> str:
    return f"actron:request:{request_id}"


def investigation(investigation_id: str) -> str:
    return f"actron:investigation:{investigation_id}"


def build(build_id: str) -> str:
    return f"actron:build:{build_id}"


def graph_name(prefix: str, ws: str) -> str:
    return f"{prefix}_{ws.replace('-', '_')}"


_QUAL_RE = re.compile(r"^(?P<repo>[^:]+/[^:]+):(?P<path>.+?)::(?P<qual>[^~]+?)(?:~(?P<dup>\d+))?$")


def parse_id(node_id: str) -> ParsedId:
    """Return the label and parts of an id. Raises InvalidId for unknown prefixes."""
    pieces = node_id.split(":", 2)
    if len(pieces) < 3:
        raise InvalidId(f"not an Actron id: {node_id!r}")
    prefix = f"{pieces[0]}:{pieces[1]}"
    label = PREFIX_LABELS.get(prefix)
    if label is None:
        raise InvalidId(f"unknown id prefix {prefix!r}")
    rest = pieces[2]
    parts: dict[str, str] = {"rest": rest}
    if prefix in ("code:fn", "code:class"):
        m = _QUAL_RE.match(rest)
        if not m:
            raise InvalidId(f"malformed {prefix} id: {node_id!r}")
        parts.update(repo=m["repo"], path=m["path"], qualname=m["qual"], dup=m["dup"] or "1")
    elif prefix == "code:file":
        repo, _, path = rest.partition(":")
        parts.update(repo=repo, path=path)
    elif prefix == "code:chunk":
        m = re.match(r"^(?P<repo>[^:]+):(?P<path>.+)#L(?P<s>\d+)-L(?P<e>\d+)$", rest)
        if not m:
            raise InvalidId(f"malformed chunk id: {node_id!r}")
        parts.update(repo=m["repo"], path=m["path"], start=m["s"], end=m["e"])
    elif prefix == "code:doc":
        repo, _, tail = rest.partition(":")
        path, _, slug = tail.rpartition("#")
        dup = "1"
        if "~" in slug:
            slug, dup = slug.rsplit("~", 1)
        parts.update(repo=repo, path=path, slug=slug, dup=dup)
    elif prefix in ("github:pr", "github:issue", "github:milestone"):
        repo, _, number = rest.partition("#")
        parts.update(repo=repo, number=number)
    elif prefix == "github:prfile":
        repo, _, tail = rest.partition("#")
        number, _, path = tail.partition(":")
        parts.update(repo=repo, number=number, path=path)
    elif prefix == "git:commit":
        repo, _, sha = rest.rpartition(":")
        parts.update(repo=repo, sha=sha)
    elif prefix == "git:change":
        repo, _, tail = rest.partition(":")
        sha, _, path = tail.partition(":")
        parts.update(repo=repo, sha=sha, path=path)
    elif prefix == "slack:msg":
        base, _, ver = rest.partition("@v")
        channel, _, ts = base.partition(":")
        parts.update(channel=channel, ts=ts)
        if ver:
            parts["version"] = ver
    return ParsedId(prefix=prefix, label=label, parts=parts)


def label_of(node_id: str) -> str:
    return parse_id(node_id).label
