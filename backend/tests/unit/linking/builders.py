"""Small builders that write synthetic, Calva-flavoured source records into a test graph.

They write what the connectors would write (spec A, A8-A10), with only the properties linking reads.
"""

from __future__ import annotations

import hashlib
from typing import Any

from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow

REPO = "betterthantomorrow/calva"
T0 = "2026-09-01T10:00:00Z"
STRUCT = {"method": "structural", "confidence": 1.0}


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def slack_user(
    g: GraphStore,
    uid: str,
    *,
    email: str | None = None,
    name: str | None = None,
    is_bot: bool = False,
) -> str:
    nid = ids.slack_user(uid)
    g.upsert_nodes(
        "SlackUser", [{"id": nid, "email": email, "realName": name, "name": name, "isBot": is_bot}]
    )
    return nid


def slack_channel(
    g: GraphStore, cid: str, *, name: str = "calva-dev", aliases: list[str] | None = None
) -> str:
    nid = ids.slack_channel(cid)
    g.upsert_nodes("SlackChannel", [{"id": nid, "name": name, "aliases": aliases}])
    return nid


def slack_msg(
    g: GraphStore,
    channel: str,
    ts: str,
    text: str,
    *,
    user: str | None = None,
    parent_ts: str | None = None,
    bot_id: str | None = None,
    at: str = T0,
    subtype: str | None = None,
) -> str:
    nid = ids.slack_msg(channel, ts)
    g.upsert_nodes(
        "SlackMessage",
        [
            {
                "id": nid,
                "text": text,
                "ts": ts,
                "channelId": channel,
                "postedAt": at,
                "userId": user,
                "botId": bot_id,
                "threadTs": parent_ts,
                "subtype": subtype,
                "name": text[:80],
            }
        ],
    )
    if user:
        uid = ids.slack_user(user)
        if not g.get_node(uid):
            slack_user(g, user)
        g.upsert_links("POSTED_BY", "SlackMessage", "SlackUser", [LinkRow(nid, uid, STRUCT)])
    if parent_ts:
        g.upsert_links(
            "THREAD_OF",
            "SlackMessage",
            "SlackMessage",
            [LinkRow(nid, ids.slack_msg(channel, parent_ts), STRUCT)],
        )
    return nid


def linear_team(g: GraphStore, key: str = "CAL") -> str:
    nid = ids.linear_team(f"team-{key.lower()}")
    g.upsert_nodes("LinearTeam", [{"id": nid, "key": key, "name": f"{key} team"}])
    return nid


def linear_user(
    g: GraphStore, uid: str, *, email: str | None = None, name: str | None = None
) -> str:
    nid = ids.linear_user(uid)
    g.upsert_nodes("LinearUser", [{"id": nid, "email": email, "name": name}])
    return nid


def linear_issue(
    g: GraphStore,
    uid: str,
    identifier: str,
    title: str,
    *,
    description: str = "",
    branch: str | None = None,
    attachments: list[str] | None = None,
) -> str:
    nid = ids.linear_issue(uid)
    g.upsert_nodes(
        "LinearIssue",
        [
            {
                "id": nid,
                "identifier": identifier,
                "title": title,
                "description": description,
                "url": f"https://linear.app/calva/issue/{identifier}",
                "branchName": branch,
                "attachmentUrls": attachments,
                "createdAt": T0,
            }
        ],
    )
    return nid


def github_user(
    g: GraphStore, numeric: int, login: str, *, email: str | None = None, name: str | None = None
) -> str:
    nid = ids.github_user(numeric)
    g.upsert_nodes("GithubUser", [{"id": nid, "login": login, "email": email, "name": name}])
    return nid


def pr(
    g: GraphStore,
    number: int,
    title: str,
    *,
    body: str = "",
    head: str = "feature",
    merged: bool = False,
    repo: str = REPO,
    files: list[str] | None = None,
    at: str = T0,
    author: str | None = None,
) -> str:
    nid = ids.github_pr(repo, number)
    g.upsert_nodes(
        "GithubPullRequest",
        [
            {
                "id": nid,
                "number": number,
                "title": title,
                "body": body,
                "state": "closed" if merged else "open",
                "merged": merged,
                "mergedAt": at if merged else None,
                "createdAt": at,
                "updatedAt": at,
                "url": f"https://github.com/{repo}/pull/{number}",
                "headRef": head,
                "baseRef": "dev",
            }
        ],
    )
    for path in files or []:
        fid = ids.github_prfile(repo, number, path)
        g.upsert_nodes("GithubPullRequestFile", [{"id": fid, "path": path, "status": "modified"}])
        g.upsert_links(
            "CHANGES_FILE",
            "GithubPullRequest",
            "GithubPullRequestFile",
            [LinkRow(nid, fid, STRUCT)],
        )
    if author:
        g.upsert_links(
            "OPENED_BY", "GithubPullRequest", "GithubUser", [LinkRow(nid, author, STRUCT)]
        )
    return nid


def git_author(g: GraphStore, email: str, name: str = "") -> str:
    nid = ids.git_author(email)
    g.upsert_nodes("GitAuthor", [{"id": nid, "email": email.lower(), "name": name}])
    return nid


def commit(
    g: GraphStore,
    sha: str,
    message: str,
    *,
    author: str | None = None,
    at: str = T0,
    touched: list[str] | None = None,
    files: list[str] | None = None,
) -> str:
    nid = ids.git_commit(REPO, sha)
    g.upsert_nodes(
        "GitCommit",
        [
            {
                "id": nid,
                "sha": sha,
                "subject": message.split("\n")[0],
                "message": message,
                "authoredAt": at,
            }
        ],
    )
    if author:
        g.upsert_links("AUTHORED_BY", "GitCommit", "GitAuthor", [LinkRow(nid, author, STRUCT)])
    for fn in touched or []:
        g.upsert_links(
            "TOUCHED",
            "GitCommit",
            "CodeFunction",
            [LinkRow(nid, fn, {**STRUCT, "changeType": "modified", "linesChanged": 3})],
        )
    for path in files or []:
        cid = ids.git_change(REPO, sha, path)
        g.upsert_nodes("GitFileChange", [{"id": cid, "path": path, "status": "modified"}])
        g.upsert_links("HAS_FILE_CHANGE", "GitCommit", "GitFileChange", [LinkRow(nid, cid, STRUCT)])
        g.upsert_links(
            "CHANGE_OF_FILE",
            "GitFileChange",
            "CodeFile",
            [LinkRow(cid, ids.code_file(REPO, path), STRUCT)],
        )
    return nid


def code_file(g: GraphStore, path: str, text: str = "") -> str:
    nid = ids.code_file(REPO, path)
    g.upsert_nodes(
        "CodeFile", [{"id": nid, "path": path, "contentHash": _h(path + text), "text": text}]
    )
    return nid


def code_fn(
    g: GraphStore,
    path: str,
    qualname: str,
    body: str,
    *,
    doc: str | None = None,
    signature: str | None = None,
) -> str:
    fid = ids.code_file(REPO, path)
    if not g.get_node(fid):
        code_file(g, path)
    nid = ids.code_fn(REPO, path, qualname)
    g.upsert_nodes(
        "CodeFunction",
        [
            {
                "id": nid,
                "name": qualname.split(".")[-1],
                "qualifiedName": qualname,
                "startLine": 1,
                "endLine": 20,
                "body": body,
                "contentHash": _h(body),
                "docstring": doc,
                "signature": signature or f"{qualname}()",
                "kind": "function",
            }
        ],
    )
    g.upsert_links("FUNCTION_DEFINED_IN", "CodeFunction", "CodeFile", [LinkRow(nid, fid, STRUCT)])
    return nid


def code_class(g: GraphStore, path: str, qualname: str, body: str) -> str:
    fid = ids.code_file(REPO, path)
    if not g.get_node(fid):
        code_file(g, path)
    nid = ids.code_class(REPO, path, qualname)
    g.upsert_nodes(
        "CodeClass",
        [
            {
                "id": nid,
                "name": qualname.split(".")[-1],
                "qualifiedName": qualname,
                "startLine": 1,
                "endLine": 40,
                "body": body,
                "contentHash": _h(body),
            }
        ],
    )
    g.upsert_links("CLASS_DEFINED_IN", "CodeClass", "CodeFile", [LinkRow(nid, fid, STRUCT)])
    return nid


def code_repo(g: GraphStore) -> str:
    nid = ids.code_repo(REPO)
    g.upsert_nodes(
        "CodeRepository",
        [
            {
                "id": nid,
                "name": "calva",
                "defaultBranch": "dev",
                "headSha": "0" * 40,
                "url": f"https://github.com/{REPO}",
            }
        ],
    )
    return nid


def node(g: GraphStore, node_id: str) -> dict[str, Any]:
    found = g.get_node(node_id)
    assert found is not None, node_id
    return found


def links(
    g: GraphStore,
    rel: str,
    from_id: str | None = None,
    to_id: str | None = None,
    *,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    where = []
    params: dict[str, Any] = {}
    if from_id:
        where.append("a.id = $a")
        params["a"] = from_id
    if to_id:
        where.append("b.id = $b")
        params["b"] = to_id
    if not include_deleted:
        where.append("coalesce(r.deleted, false) = false")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = g.query(
        f"MATCH (a)-[r:`{rel}`]->(b){clause} RETURN a.id AS a, b.id AS b, properties(r) AS p",
        params,
    )
    return [{"from": r["a"], "to": r["b"], **dict(r["p"])} for r in rows]
