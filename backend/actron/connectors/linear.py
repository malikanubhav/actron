"""Linear connector (spec A, A10): teams, users, states, labels, projects, issues with comments.

Incremental by `updatedAt`: the issue query filters `updatedAt > cursor` and orders newest first, so the
cursor moves to the newest `updatedAt` only when the last page is done. Edits to an issue's title or
description, or to a comment's body, keep the previous text as a version node. Attachment URLs go to
`LinearIssue.attachmentUrls` for linking.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from actron.connectors.common import (
    Batch,
    WriteResult,
    decode_token,
    encode_token,
    write_generic,
)
from actron.connectors.steps import SOURCE_STEPS
from actron.graph import ids
from actron.graph.store import GraphStore, store_for
from actron.integrations import linear_client as lc
from actron.integrations.linear_client import LinearClient, deterministic_issue_id
from actron.logging import get_logger

log = get_logger(__name__)

STEPS: list[str] = SOURCE_STEPS["linear"]
__all__ = ["STEPS", "detect_external_edit", "deterministic_issue_id", "fetch_page", "write_batch"]


# Mapping
def team_row(t: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": ids.linear_team(t["id"]), "name": t["name"], "key": t.get("key"),
            "description": t.get("description"), "createdAt": t.get("createdAt"), "updatedAt": t.get("updatedAt")}


def user_row(u: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": ids.linear_user(u["id"]), "name": u.get("name") or u["id"], "email": u.get("email"),
            "isAdmin": u.get("admin"), "lastActive": u.get("lastSeen"), "avatarUrl": u.get("avatarUrl"),
            "displayName": u.get("displayName"), "active": u.get("active")}


def state_row(s: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": ids.linear_state(s["id"]), "name": s["name"], "type": s.get("type"), "color": s.get("color"),
            "position": s.get("position"), "teamId": (s.get("team") or {}).get("id")}


def label_row(label: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": ids.linear_label(label["id"]), "name": label["name"], "color": label.get("color"),
            "teamId": (label.get("team") or {}).get("id"), "groupId": (label.get("parent") or {}).get("id")}


def project_row(p: Mapping[str, Any]) -> dict[str, Any]:
    teams = (p.get("teams") or {}).get("nodes") or []
    return {"id": ids.linear_project(p["id"]), "name": p["name"], "description": p.get("description"),
            "status": p.get("state"), "leadId": (p.get("lead") or {}).get("id"),
            "teamId": teams[0]["id"] if teams else None, "startDate": p.get("startDate"),
            "targetDate": p.get("targetDate"), "createdAt": p.get("createdAt"), "updatedAt": p.get("updatedAt")}


def issue_row(i: Mapping[str, Any]) -> dict[str, Any]:
    state = i.get("state") or {}
    attachments = [a["url"] for a in (i.get("attachments") or {}).get("nodes", []) if a.get("url")]
    return {
        "id": ids.linear_issue(i["id"]), "title": i["title"], "description": i.get("description"),
        "priority": i.get("priority"), "assigneeId": (i.get("assignee") or {}).get("id"),
        "stateId": state.get("id"), "teamId": (i.get("team") or {}).get("id"),
        "projectId": (i.get("project") or {}).get("id"),
        "labelIds": [n["id"] for n in (i.get("labels") or {}).get("nodes", [])] or None,
        "dueDate": i.get("dueDate"), "createdAt": i.get("createdAt"), "updatedAt": i.get("updatedAt"),
        "number": i.get("number"), "identifier": i.get("identifier"), "url": i["url"],
        "sourceUrl": i["url"], "creatorId": (i.get("creator") or {}).get("id"),
        "parentId": (i.get("parent") or {}).get("id"), "branchName": i.get("branchName"),
        "stateType": state.get("type"), "estimate": float(i["estimate"]) if i.get("estimate") is not None else None,
        "completedAt": i.get("completedAt"), "canceledAt": i.get("canceledAt"),
        "attachmentUrls": attachments or None, "version": 1,
    }


def comment_row(issue_uuid: str, c: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": ids.linear_comment(c["id"]), "issueId": issue_uuid, "body": c.get("body") or "",
            "authorId": (c.get("user") or {}).get("id"), "parentId": (c.get("parent") or {}).get("id"),
            "editedAt": c.get("editedAt"), "createdAt": c.get("createdAt"), "url": c.get("url"),
            "sourceUrl": c.get("url"), "updatedAt": c.get("updatedAt"), "version": 1}


_MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9][A-Za-z0-9._-]{0,39})")


def mentioned_users(body: str, handles: Mapping[str, str]) -> list[str]:
    """User uuids for `@handle` mentions; handles are lowercased display names or names."""
    out: list[str] = []
    for m in _MENTION.finditer(body or ""):
        uid = handles.get(m.group(1).lower())
        if uid and uid not in out:
            out.append(uid)
    return out


def map_issue(b: Batch, issue: Mapping[str, Any], comments: Sequence[Mapping[str, Any]],
              handles: Mapping[str, str]) -> None:
    row = issue_row(issue)
    iid = row["id"]
    b.extra.setdefault("issues", []).append(row)
    if row.get("teamId"):
        b.add_link("BELONGS_TO_TEAM", "LinearIssue", iid, "LinearTeam", ids.linear_team(row["teamId"]))
    if row.get("stateId"):
        b.add_link("HAS_STATE", "LinearIssue", iid, "LinearState", ids.linear_state(row["stateId"]))
    if row.get("assigneeId"):
        b.add_link("ASSIGNED_TO", "LinearIssue", iid, "LinearUser", ids.linear_user(row["assigneeId"]))
    if row.get("creatorId"):
        b.add_link("ISSUE_CREATED_BY", "LinearIssue", iid, "LinearUser", ids.linear_user(row["creatorId"]))
    if row.get("projectId"):
        b.add_link("BELONGS_TO_PROJECT", "LinearIssue", iid, "LinearProject", ids.linear_project(row["projectId"]))
        b.add_link("CONTAINS_ISSUE", "LinearProject", ids.linear_project(row["projectId"]), "LinearIssue", iid)
    if row.get("parentId"):
        b.add_link("SUBISSUE_OF", "LinearIssue", iid, "LinearIssue", ids.linear_issue(row["parentId"]))
    for label_id in row.get("labelIds") or []:
        b.add_link("HAS_LABEL", "LinearIssue", iid, "LinearLabel", ids.linear_label(label_id))
    for c in comments:
        crow = comment_row(issue["id"], c)
        b.extra.setdefault("comments", []).append(crow)
        cid = crow["id"]
        b.add_link("HAS_COMMENT", "LinearIssue", iid, "LinearComment", cid)
        if crow.get("authorId"):
            b.add_link("CREATED_BY", "LinearComment", cid, "LinearUser", ids.linear_user(crow["authorId"]))
        if crow.get("parentId"):
            b.add_link("REPLIES_TO", "LinearComment", cid, "LinearComment", ids.linear_comment(crow["parentId"]))
        for uid in mentioned_users(crow["body"], handles):
            b.add_link("MENTIONS_USER", "LinearComment", cid, "LinearUser", ids.linear_user(uid),
                       method="explicit")


# Fetching
async def fetch_page(ws: str, step: str, cursor: Mapping[str, Any], page_token: str | None,
                     config: Mapping[str, Any]) -> Batch:
    if step not in STEPS:
        raise ValueError(f"unknown Linear step {step!r}")
    batch = Batch(step=step)
    tok = decode_token(page_token)
    async with LinearClient(config.get("token"), base_url=config.get("api_url")) as client:
        await _HANDLERS[step](ws, client, cursor, tok, config, batch)
        batch.meta["requests"] = client.requests_made
    return batch


def _team_scope(config: Mapping[str, Any], teams: Sequence[Mapping[str, Any]]) -> list[str]:
    wanted = config.get("team")
    if wanted:
        return [t["id"] for t in teams if wanted in (t["id"], t.get("key"), t.get("name"))] or [str(wanted)]
    return [t["id"] for t in teams]


async def _step_teams(ws: str, client: LinearClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                      config: Mapping[str, Any], b: Batch) -> None:
    nodes, nxt = await client.connection(lc.Q_TEAMS, "teams", {"after": tok.get("a")})
    for t in nodes:
        b.add_node("LinearTeam", team_row(t))
    scope = list(cursor.get("_teams") or []) if tok.get("a") else []
    scope.extend(_team_scope(config, nodes))
    b.cursor_update["_teams"] = sorted(set(scope))
    b.next_page_token = encode_token({"a": nxt}) if nxt else None


async def _step_users(ws: str, client: LinearClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                      config: Mapping[str, Any], b: Batch) -> None:
    nodes, nxt = await client.connection(lc.Q_USERS, "users", {"after": tok.get("a")})
    for u in nodes:
        b.add_node("LinearUser", user_row(u))
    b.next_page_token = encode_token({"a": nxt}) if nxt else None


async def _per_team(ws: str, client: LinearClient, cursor: Mapping[str, Any], tok: dict[str, Any], b: Batch,
                    query: str, key: str, handle: Callable[[Mapping[str, Any], str], None]) -> None:
    teams = list(cursor.get("_teams") or [])
    i = int(tok.get("i", 0))
    if i >= len(teams):
        return
    team = teams[i]
    nodes, nxt = await client.connection(query, key, {"team": team, "after": tok.get("a")})
    for n in nodes:
        handle(n, team)
    if nxt:
        b.next_page_token = encode_token({"i": i, "a": nxt})
    elif i + 1 < len(teams):
        b.next_page_token = encode_token({"i": i + 1})


async def _step_states(ws: str, client: LinearClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                       config: Mapping[str, Any], b: Batch) -> None:
    def handle(s: Mapping[str, Any], team: str) -> None:
        row = state_row({**s, "team": s.get("team") or {"id": team}})
        b.add_node("LinearState", row)
        b.add_link("DEFINES_WORKFLOW", "LinearTeam", ids.linear_team(team), "LinearState", row["id"])

    await _per_team(ws, client, cursor, tok, b, lc.Q_STATES, "workflowStates", handle)


async def _step_labels(ws: str, client: LinearClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                       config: Mapping[str, Any], b: Batch) -> None:
    def handle(label: Mapping[str, Any], team: str) -> None:
        row = label_row({**label, "team": label.get("team") or {"id": team}})
        b.add_node("LinearLabel", row)
        b.add_link("USES_LABEL", "LinearTeam", ids.linear_team(team), "LinearLabel", row["id"])

    await _per_team(ws, client, cursor, tok, b, lc.Q_LABELS, "issueLabels", handle)


async def _step_projects(ws: str, client: LinearClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                         config: Mapping[str, Any], b: Batch) -> None:
    nodes, nxt = await client.connection(lc.Q_PROJECTS, "projects", {"after": tok.get("a")})
    scope = set(cursor.get("_teams") or [])
    for p in nodes:
        team_ids = {t["id"] for t in (p.get("teams") or {}).get("nodes", [])}
        if scope and team_ids and not (team_ids & scope):
            continue
        b.add_node("LinearProject", project_row(p))
    b.next_page_token = encode_token({"a": nxt}) if nxt else None


def default_since(config: Mapping[str, Any]) -> str:
    days = int(config.get("history_days") or 90)
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def _handles(ws: str) -> dict[str, str]:
    store = store_for(ws)
    rows = await asyncio.to_thread(
        store.query, "MATCH (u:LinearUser) RETURN u.id AS id, u.name AS name, u.displayName AS display",
        None, read_only=True)
    out: dict[str, str] = {}
    for r in rows:
        uid = r["id"].removeprefix("linear:user:")
        for handle in (r.get("display"), r.get("name")):
            if handle:
                out.setdefault(str(handle).lower(), uid)
                out.setdefault(str(handle).split()[0].lower(), uid)
    return out


async def _step_issues(ws: str, client: LinearClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                       config: Mapping[str, Any], b: Batch) -> None:
    teams = list(cursor.get("_teams") or [])
    i = int(tok.get("i", 0))
    if i >= len(teams):
        return
    team = teams[i]
    since = str(cursor.get("issues_updated") or default_since(config))
    nodes, nxt = await client.connection(lc.Q_ISSUES, "issues", {"team": team, "since": since, "after": tok.get("a")})
    handles = await _handles(ws)
    # attach `handles` for users that arrive in the same run: _handles reads the graph, users step ran before
    newest = tok.get("m")
    for issue in nodes:
        comments = list((issue.get("comments") or {}).get("nodes") or [])
        info = (issue.get("comments") or {}).get("pageInfo") or {}
        if info.get("hasNextPage"):
            comments.extend(await client.all_comments(issue["id"], info.get("endCursor")))
        map_issue(b, issue, comments, handles)
        newest = max(newest or "", issue["updatedAt"])
    if nxt:
        b.next_page_token = encode_token({"i": i, "a": nxt, "m": newest})
        return
    if i + 1 < len(teams):  # the cursor moves only after the last team, so every team reads from the old one
        b.next_page_token = encode_token({"i": i + 1, "m": newest})
        return
    if newest:
        b.cursor_update["issues_updated"] = max(newest, str(cursor.get("issues_updated") or ""))


_HANDLERS: dict[str, Callable[..., Awaitable[None]]] = {
    "teams": _step_teams, "users": _step_users, "states": _step_states, "labels": _step_labels,
    "projects": _step_projects, "issues": _step_issues,
}


# Writing
def _existing(store: GraphStore, label: str, node_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(node_ids), 500):
        rows = store.query(
            f"MATCH (n:`{label}`) WHERE n.id IN $ids RETURN n.id AS id, n.title AS title, "
            "n.description AS description, n.body AS body, n.version AS version",
            {"ids": list(node_ids[i : i + 500])}, read_only=True)
        for r in rows:
            out[r["id"]] = r
    return out


def _version(store: GraphStore, label: str, node_id: str, props: Mapping[str, Any]) -> int:
    """Copy the node to `@v<n>`, link it and apply the new properties (A4, same shape as Slack edits)."""
    from actron.graph.store import LinkRow, to_graph_value

    rel = "ISSUE_PREVIOUS_VERSION" if label == "LinearIssue" else "COMMENT_PREVIOUS_VERSION"
    old = store.get_node(node_id)
    if old is None:
        raise LookupError(node_id)
    n = int(old.get("version") or 1)
    copy_row = {k: v for k, v in old.items() if not k.startswith("_")}
    copy_row["id"] = f"{node_id}@v{n}"
    copy_row["version"] = n
    store.upsert_nodes(label, [copy_row], partial=True)
    link = {"method": "structural", "confidence": 1.0, "version": n}
    if n > 1:
        store.delete_links(rel, label, label, [(node_id, f"{node_id}@v{n - 1}")])
        store.upsert_links(rel, label, label, [LinkRow(copy_row["id"], f"{node_id}@v{n - 1}", link | {"version": n - 1})])
    store.upsert_links(rel, label, label, [LinkRow(node_id, copy_row["id"], link)])
    changes: dict[str, Any] = {"id": node_id, **{k: to_graph_value(v) for k, v in props.items()}, "version": n + 1}
    store.update_nodes(label, [changes])
    return n + 1


def write_batch(ws: str, step: str, batch: Batch) -> WriteResult:
    store = store_for(ws)
    changed: list[str] = []
    counts: dict[str, int] = {}
    # Dependencies first: projects, labels, states and users are written by write_generic below, but issue and
    # comment rows are planned here (new, edited, unchanged) and written before their links.
    issues = batch.extra.get("issues", [])
    comments = batch.extra.get("comments", [])
    pre = write_generic(ws, Batch(step=step, nodes=batch.nodes), store=store) if batch.nodes else WriteResult()
    for k, v in pre.counts.items():
        counts[k] = counts.get(k, 0) + v
    if issues:
        have = _existing(store, "LinearIssue", [r["id"] for r in issues])
        fresh = [r for r in issues if r["id"] not in have]
        if fresh:
            counts["LinearIssue"] = counts.get("LinearIssue", 0) + store.upsert_nodes("LinearIssue", fresh)
            changed.extend(r["id"] for r in fresh)
        for row in (r for r in issues if r["id"] in have):
            old = have[row["id"]]
            text_changed = (old.get("title") or "") != row["title"] or (old.get("description") or "") != (
                row.get("description") or "")
            props = {k: v for k, v in row.items() if k not in ("id", "version") and v is not None}
            if text_changed:
                _version(store, "LinearIssue", row["id"], props)
                counts["LinearIssue"] = counts.get("LinearIssue", 0) + 1
                changed.append(row["id"])
            else:
                store.update_nodes("LinearIssue", [{"id": row["id"], **{k: v for k, v in props.items()
                                                                          if k != "createdAt"}}])
    if comments:
        have_c = _existing(store, "LinearComment", [r["id"] for r in comments])
        fresh_c = [r for r in comments if r["id"] not in have_c]
        if fresh_c:
            counts["LinearComment"] = counts.get("LinearComment", 0) + store.upsert_nodes("LinearComment", fresh_c)
            changed.extend(r["id"] for r in fresh_c)
        for row in (r for r in comments if r["id"] in have_c):
            if (have_c[row["id"]].get("body") or "") != row["body"]:
                props = {k: v for k, v in row.items() if k not in ("id", "version") and v is not None}
                _version(store, "LinearComment", row["id"], props)
                counts["LinearComment"] = counts.get("LinearComment", 0) + 1
                changed.append(row["id"])
    rest = Batch(step=step, links=batch.links, only_if_missing=batch.only_if_missing, tombstones=batch.tombstones)
    result = write_generic(ws, rest, store=store)
    for k, v in counts.items():
        result.counts[k] = result.counts.get(k, 0) + v
    result.changed_ids = list(dict.fromkeys(changed))
    return result


# External edit detection (A10, spec B ticket format)
_MARKER = re.compile(r"<!--\s*actron:ticket\s+sha256=([0-9a-f]{64})(?:\s+rev=(\d+))?\s*-->")
_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def canonical_ticket_json(ticket: Mapping[str, Any]) -> str:
    body = {k: v for k, v in ticket.items() if k != "revision"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ticket_hash(ticket: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_ticket_json(ticket).encode("utf-8")).hexdigest()


@dataclass
class ExternalEdit:
    edited: bool
    reason: str | None = None
    found_hash: str | None = None
    revision: int | None = None


def detect_external_edit(description: str | None, expected_hash: str) -> ExternalEdit:
    """True when the issue description no longer matches the ticket revision Actron wrote.

    The description holds the ticket as markdown, a marker `<!-- actron:ticket sha256=<hash> rev=<n> -->` and a
    fenced JSON block with the canonical ticket. It is untouched only when the marker, the recomputed hash of
    the block and `expected_hash` all agree.
    """
    text = description or ""
    marker = _MARKER.search(text)
    if marker is None:
        return ExternalEdit(True, "the ticket marker is missing")
    found = marker.group(1)
    rev = int(marker.group(2)) if marker.group(2) else None
    block = _BLOCK.search(text[marker.end():]) or _BLOCK.search(text)
    if block is None:
        return ExternalEdit(True, "the ticket JSON block is missing", found, rev)
    try:
        ticket = json.loads(block.group(1))
    except ValueError:
        return ExternalEdit(True, "the ticket JSON block is not valid JSON", found, rev)
    if not isinstance(ticket, dict):
        return ExternalEdit(True, "the ticket JSON block is not an object", found, rev)
    recomputed = ticket_hash(ticket)
    if recomputed != found:
        return ExternalEdit(True, "the ticket content no longer matches its hash", found, rev)
    if found != expected_hash:
        return ExternalEdit(True, "the ticket hash differs from the approved revision", found, rev)
    return ExternalEdit(False, None, found, rev)
