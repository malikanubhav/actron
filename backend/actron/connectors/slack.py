"""Slack connector (spec A, A9): backfill, incremental catch-up, live events, edits and deletes.

Steps (one activity per page): workspace, users, channels, members, history, replies. Messages are
planned against what the graph already holds, so a catch-up writes only new or changed messages.
Edits keep the old text as a previous version (`actron.graph.versions`); deletes become tombstones.
Reactions and files come from the message itself.

`handle_message_event` is the entry point for live events (the Slack bot calls it).
"""

from __future__ import annotations

import asyncio
import html
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from actron.connectors.common import (
    Batch,
    WriteResult,
    decode_token,
    encode_token,
    existing_ids,
    write_generic,
)
from actron.connectors.steps import SOURCE_STEPS
from actron.graph import ids
from actron.graph.store import GraphStore, store_for
from actron.graph.versions import NodeNotFound, version_slack_message
from actron.integrations.slack_client import SlackApiError, SlackClient
from actron.logging import get_logger

log = get_logger(__name__)

STEPS: list[str] = SOURCE_STEPS["slack"]

SKIPPED_SUBTYPES = frozenset({"channel_join", "channel_leave", "group_join", "group_leave", "channel_archive",
                              "channel_unarchive", "pinned_item", "unpinned_item"})
BOT_SUBTYPE = "bot_message"
EDIT_LOOKBACK = timedelta(hours=24)
MAX_MESSAGES_PER_CHANNEL = 20000
REFERENCE_RELS = ("MENTIONS", "CONTAINS_REFERENCE")


# Text normalisation (A-AC-54). Raw mrkdwn stays in `text`; this plain form is for linking and display.
_TAG = re.compile(r"<([^<>]+)>")


def _tag_text(inner: str, users: Mapping[str, str], channels: Mapping[str, str]) -> str:
    target, _, label = inner.partition("|")
    if target.startswith("@"):
        uid = target[1:]
        return "@" + (label or users.get(uid) or uid)
    if target.startswith("#"):
        cid = target[1:]
        return "#" + (label or channels.get(cid) or cid)
    if target.startswith("!"):
        special = target[1:]
        if special in ("here", "channel", "everyone"):
            return "@" + special
        if special.startswith("subteam^"):
            return label if label else "@usergroup"
        if special.startswith("date"):
            return label or special.split("^")[-1]
        return label or "@" + special.split("^")[0]
    if target.startswith("mailto:"):
        address = target[len("mailto:"):]
        return label if label and label != address else address
    if label and label != target:
        return f"{label} ({target})"
    return target


def normalize_slack_text(text: str, users: Mapping[str, str] | None = None,
                         channels: Mapping[str, str] | None = None) -> str:
    """User mentions to `@name`, channels to `#name`, links to `label (url)`, entities unescaped."""
    users = users or {}
    channels = channels or {}
    replaced = _TAG.sub(lambda m: _tag_text(m.group(1), users, channels), text)
    return html.unescape(replaced)


# Time and ids
def ts_to_iso(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def ts_from_datetime(when: datetime) -> str:
    return f"{when.timestamp():.6f}"


def permalink(domain: str | None, channel: str, ts: str) -> str | None:
    if not domain:
        return None
    return f"https://{domain}.slack.com/archives/{channel}/p{ts.replace('.', '')}"


@dataclass
class MsgCtx:
    domain: str | None = None
    bot_user_id: str | None = None
    workspace_id: str | None = None


def ctx_from_cursor(cursor: Mapping[str, Any]) -> MsgCtx:
    w = cursor.get("workspace") or {}
    return MsgCtx(w.get("domain"), w.get("bot_user_id"), w.get("id"))


# Mapping
def message_row(channel: str, raw: Mapping[str, Any], ctx: MsgCtx) -> dict[str, Any]:
    ts = str(raw["ts"])
    text = raw.get("text") or ""
    subtype = raw.get("subtype")
    bot_id = raw.get("bot_id")
    if not subtype and (bot_id or (ctx.bot_user_id and raw.get("user") == ctx.bot_user_id)):
        subtype = BOT_SUBTYPE
    edited = raw.get("edited") or {}
    thread_ts = raw.get("thread_ts")
    return {
        "id": ids.slack_msg(channel, ts), "name": text[:80], "text": text, "ts": ts,
        "threadTs": thread_ts, "channelId": channel, "userId": raw.get("user"), "subtype": subtype,
        "replyCount": raw.get("reply_count"), "permalink": permalink(ctx.domain, channel, ts),
        "edited": True if edited else None, "editedAt": ts_to_iso(edited["ts"]) if edited.get("ts") else None,
        "postedAt": ts_to_iso(ts), "version": 1, "botId": bot_id, "sourceUrl": permalink(ctx.domain, channel, ts),
    }


def message_extras(b: Batch, channel: str, raw: Mapping[str, Any], row: Mapping[str, Any], ctx: MsgCtx,
                   *, with_reactions: bool = True) -> set[str]:
    """Links, reactions and files for one message. Returns the reaction ids it carries."""
    mid = row["id"]
    ts = str(raw["ts"])
    b.add_link("RELATED_TO_CHANNEL", "SlackMessage", mid, "SlackChannel", ids.slack_channel(channel))
    if ctx.workspace_id:
        b.add_link("RELATED_TO", "SlackMessage", mid, "SlackWorkspace", ids.slack_workspace(ctx.workspace_id))
    if raw.get("user"):
        b.add_link("POSTED_BY", "SlackMessage", mid, "SlackUser", ids.slack_user(raw["user"]))
    thread_ts = raw.get("thread_ts")
    if thread_ts and thread_ts != ts:
        b.add_link("THREAD_OF", "SlackMessage", mid, "SlackMessage", ids.slack_msg(channel, thread_ts))
    reaction_ids: set[str] = set()
    if with_reactions:
        for reaction in raw.get("reactions") or []:
            rid = ids.slack_reaction(channel, ts, reaction["name"])
            reaction_ids.add(rid)
            b.add_node("SlackReaction", {"id": rid, "name": reaction["name"]})
            b.add_link("RELATED_TO_REACTION", "SlackMessage", mid, "SlackReaction", rid)
    for f in raw.get("files") or []:
        if not f.get("id"):
            continue
        fid = ids.slack_file(f["id"])
        b.add_node("SlackFile", {"id": fid, "name": f.get("name") or f.get("title") or f["id"]})
        b.add_link("RELATED_TO_FILE", "SlackMessage", mid, "SlackFile", fid)
    return reaction_ids


def user_row(u: Mapping[str, Any]) -> dict[str, Any]:
    profile = u.get("profile") or {}
    return {
        "id": ids.slack_user(u["id"]), "name": u.get("name") or u["id"],
        "realName": u.get("real_name") or profile.get("real_name"),
        "displayName": profile.get("display_name") or None, "email": profile.get("email"),
        "title": profile.get("title") or None, "isBot": bool(u.get("is_bot")),
        "isDeleted": bool(u.get("deleted")), "avatarUrl": profile.get("image_72"),
    }


def channel_row(c: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": ids.slack_channel(c["id"]), "name": c.get("name") or c["id"],
        "isPrivate": bool(c.get("is_private")), "isArchived": bool(c.get("is_archived")),
        "topic": (c.get("topic") or {}).get("value") or None,
        "purpose": (c.get("purpose") or {}).get("value") or None, "memberCount": c.get("num_members"),
    }


# Planning against the graph: what is new, what was edited, what only needs a reply count
@dataclass
class Plan:
    new: list[str] = field(default_factory=list)
    edited: list[str] = field(default_factory=list)
    parents_with_replies: list[tuple[str, str]] = field(default_factory=list)


def _existing_state(store: GraphStore, node_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(node_ids), 500):
        rows = store.query(
            "MATCH (m:SlackMessage) WHERE m.id IN $ids "
            "OPTIONAL MATCH (m)-[:RELATED_TO_REACTION]->(r:SlackReaction) "
            "RETURN m.id AS id, m.text AS text, m.editedAt AS editedAt, m.replyCount AS replyCount, "
            "m.deleted AS deleted, collect(r.id) AS reactions",
            {"ids": list(node_ids[i : i + 500])}, read_only=True)
        for r in rows:
            out[r["id"]] = r
    return out


def plan_messages(store: GraphStore, b: Batch, channel: str, raws: Sequence[Mapping[str, Any]], ctx: MsgCtx,
                  *, since_ts: str | None = None) -> Plan:
    """Sort messages into new, edited and unchanged and add what must be written to `b`."""
    plan = Plan()
    usable = [r for r in raws if r.get("subtype") not in SKIPPED_SUBTYPES and r.get("ts")]
    state = _existing_state(store, [ids.slack_msg(channel, str(r["ts"])) for r in usable])
    messages: list[dict[str, Any]] = b.extra.setdefault("messages", [])
    for raw in usable:
        row = message_row(channel, raw, ctx)
        mid = row["id"]
        have = state.get(mid)
        if have is None:
            message_extras(b, channel, raw, row, ctx)
            messages.append({"op": "new", "row": row})
            plan.new.append(mid)
            _reply_candidate(plan, channel, raw, since_ts, new=True)
            continue
        if have.get("deleted"):
            continue
        changed = (have.get("text") or "") != row["text"] or (
            row.get("editedAt") and row["editedAt"] != have.get("editedAt"))
        if changed:
            message_extras(b, channel, raw, row, ctx)
            messages.append({"op": "edit", "row": row})
            plan.edited.append(mid)
        else:
            new_reactions = {ids.slack_reaction(channel, str(raw["ts"]), r["name"])
                             for r in raw.get("reactions") or []}
            old_reactions = set(have.get("reactions") or [])
            if new_reactions != old_reactions:
                message_extras(b, channel, raw, row, ctx)
                gone = sorted(old_reactions - new_reactions)
                if gone:
                    b.extra.setdefault("unlink_reactions", []).extend([[mid, g] for g in gone])
            if (row.get("replyCount") or 0) != (have.get("replyCount") or 0):
                messages.append({"op": "touch", "row": {"id": mid, "replyCount": row.get("replyCount")}})
        _reply_candidate(plan, channel, raw, since_ts, new=False,
                         reply_count_changed=(row.get("replyCount") or 0) != (have.get("replyCount") or 0))
    return plan


def _reply_candidate(plan: Plan, channel: str, raw: Mapping[str, Any], since_ts: str | None, *, new: bool,
                     reply_count_changed: bool = False) -> None:
    if int(raw.get("reply_count") or 0) <= 0:
        return
    if raw.get("thread_ts") not in (None, raw.get("ts")):
        return
    latest = raw.get("latest_reply")
    if new or reply_count_changed or (latest and since_ts is None) or (latest and since_ts and float(latest) > float(since_ts)):
        plan.parents_with_replies.append((channel, str(raw["ts"])))


# Fetching
async def _client_for(config: Mapping[str, Any]) -> SlackClient:
    return SlackClient(config.get("token"), base_url=config.get("api_url"))


def _selected(channel: Mapping[str, Any], wanted: Sequence[str]) -> bool:
    if not wanted:
        return bool(channel.get("is_member"))
    names = {w.lstrip("#") for w in wanted}
    return channel["id"] in names or channel.get("name") in names


async def fetch_page(ws: str, step: str, cursor: Mapping[str, Any], page_token: str | None,
                     config: Mapping[str, Any]) -> Batch:
    if step not in STEPS:
        raise ValueError(f"unknown Slack step {step!r}")
    batch = Batch(step=step)
    tok = decode_token(page_token)
    async with SlackClient(config.get("token"), base_url=config.get("api_url")) as client:
        await _HANDLERS[step](ws, client, cursor, tok, config, batch)
    return batch


async def _step_workspace(ws: str, client: SlackClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                          config: Mapping[str, Any], b: Batch) -> None:
    auth = await client.auth_test()
    team = (await client.team_info()).get("team", {})
    team_id = team.get("id") or auth["team_id"]
    domain = team.get("domain")
    b.add_node("SlackWorkspace", {"id": ids.slack_workspace(team_id), "name": team.get("name") or auth.get("team"),
                                  "domain": domain})
    b.cursor_update["workspace"] = {"id": team_id, "domain": domain, "bot_user_id": auth.get("user_id"),
                                    "bot_id": auth.get("bot_id")}


async def _step_users(ws: str, client: SlackClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                      config: Mapping[str, Any], b: Batch) -> None:
    body = await client.users_list(tok.get("c"))
    wid = (cursor.get("workspace") or {}).get("id")
    for u in body.get("members", []):
        if u.get("id") == "USLACKBOT":
            continue
        row = user_row(u)
        b.add_node("SlackUser", row)
        if wid:
            b.add_link("RELATED_TO", "SlackUser", row["id"], "SlackWorkspace", ids.slack_workspace(wid))
    nxt = (body.get("response_metadata") or {}).get("next_cursor")
    b.next_page_token = encode_token({"c": nxt}) if nxt else None


async def _step_channels(ws: str, client: SlackClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                         config: Mapping[str, Any], b: Batch) -> None:
    body = await client.conversations_list(tok.get("c"))
    wanted = list(config.get("channels") or [])
    wid = (cursor.get("workspace") or {}).get("id")
    readable: list[str] = list(cursor.get("_readable") or []) if tok.get("c") else []
    for c in body.get("channels", []):
        if wanted and not _selected(c, wanted):
            continue
        if not wanted and not c.get("is_member"):
            continue
        if not c.get("is_member"):
            b.add_error("skip_channel", f"the bot is not in #{c.get('name')}; invite Actron with /invite @Actron")
            continue
        row = channel_row(c)
        b.add_node("SlackChannel", row)
        readable.append(c["id"])
        if wid:
            b.add_link("RELATED_TO", "SlackChannel", row["id"], "SlackWorkspace", ids.slack_workspace(wid))
    nxt = (body.get("response_metadata") or {}).get("next_cursor")
    b.cursor_update["_readable"] = sorted(set(readable))
    b.next_page_token = encode_token({"c": nxt}) if nxt else None
    if not nxt and wanted:
        found = set(readable) | {n for c in body.get("channels", []) for n in (c["id"], c.get("name"))}
        for w in wanted:
            if w.lstrip("#") not in found and w.lstrip("#") not in readable:
                b.add_error("skip_channel", f"channel {w} was not found")


async def _step_members(ws: str, client: SlackClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                        config: Mapping[str, Any], b: Batch) -> None:
    channels = list(cursor.get("_readable") or [])
    i = int(tok.get("i", 0))
    if i >= len(channels):
        return
    cid = channels[i]
    try:
        body = await client.conversations_members(cid, tok.get("c"))
    except SlackApiError as exc:
        b.add_error("members", f"{cid}: {exc.code}")
        body = {}
    for uid in body.get("members", []):
        b.add_link("RELATED_TO_CHANNEL", "SlackUser", ids.slack_user(uid), "SlackChannel", ids.slack_channel(cid))
    nxt = (body.get("response_metadata") or {}).get("next_cursor")
    if nxt:
        b.next_page_token = encode_token({"i": i, "c": nxt})
    elif i + 1 < len(channels):
        b.next_page_token = encode_token({"i": i + 1})


def default_oldest(config: Mapping[str, Any]) -> str:
    days = int(config.get("history_days") or 90)
    return ts_from_datetime(datetime.now(UTC) - timedelta(days=days))


async def _step_history(ws: str, client: SlackClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                        config: Mapping[str, Any], b: Batch) -> None:
    channels = list(cursor.get("_readable") or [])
    i = int(tok.get("i", 0))
    if i >= len(channels):
        return
    cid = channels[i]
    stored_oldest = ((cursor.get("channels") or {}).get(cid) or {}).get("oldest")
    since = stored_oldest
    if stored_oldest:
        oldest = ts_from_datetime(datetime.fromtimestamp(float(stored_oldest), UTC) - EDIT_LOOKBACK)
    else:
        oldest = default_oldest(config)
    first_call = not tok
    if first_call:
        b.cursor_update["_reply_parents"] = []
    try:
        body = await client.conversations_history(cid, oldest=oldest, cursor=tok.get("c"))
    except SlackApiError as exc:
        b.add_error("history", f"{cid}: {exc.code}")
        _advance(b, channels, i, None, None)
        return
    raws = body.get("messages", [])
    ctx = ctx_from_cursor(cursor)
    store = store_for(ws)
    plan = await asyncio.to_thread(plan_messages, store, b, cid, raws, ctx, since_ts=since)
    parents = [] if first_call else list(cursor.get("_reply_parents") or [])
    parents.extend([list(p) for p in plan.parents_with_replies])
    b.cursor_update["_reply_parents"] = parents
    seen = int(tok.get("n", 0)) + len(raws)
    newest: float | None = float(tok["m"]) if tok.get("m") else None
    for r in raws:
        newest = float(r["ts"]) if newest is None else max(newest, float(r["ts"]))
    nxt = (body.get("response_metadata") or {}).get("next_cursor")
    capped = bool(nxt) and seen >= MAX_MESSAGES_PER_CHANNEL
    if capped:
        b.partial_reason = f"channel {cid} capped at {MAX_MESSAGES_PER_CHANNEL} messages"
    if nxt and not capped:
        b.next_page_token = encode_token({"i": i, "c": nxt, "n": seen, "m": newest})
        return
    _advance(b, channels, i, newest, stored_oldest, cid=cid)


def _advance(b: Batch, channels: list[str], i: int, newest: float | None,
             stored_oldest: str | None, cid: str | None = None) -> None:
    if cid and newest is not None and (stored_oldest is None or newest > float(stored_oldest)):
        b.cursor_update.setdefault("channels", {})[cid] = {"oldest": f"{newest:.6f}"}
    if i + 1 < len(channels):
        b.next_page_token = encode_token({"i": i + 1})


async def _step_replies(ws: str, client: SlackClient, cursor: Mapping[str, Any], tok: dict[str, Any],
                        config: Mapping[str, Any], b: Batch) -> None:
    parents = [tuple(p) for p in cursor.get("_reply_parents") or []]
    i = int(tok.get("i", 0))
    if i >= len(parents):
        b.cursor_update["_reply_parents"] = None
        return
    cid, ts = parents[i]
    try:
        body = await client.conversations_replies(cid, ts, tok.get("c"))
    except SlackApiError as exc:
        b.add_error("replies", f"{cid}/{ts}: {exc.code}")
        body = {}
    replies = [m for m in body.get("messages", []) if m.get("ts") != ts]
    ctx = ctx_from_cursor(cursor)
    store = store_for(ws)
    await asyncio.to_thread(plan_messages, store, b, cid, replies, ctx)
    nxt = (body.get("response_metadata") or {}).get("next_cursor")
    if nxt:
        b.next_page_token = encode_token({"i": i, "c": nxt})
    elif i + 1 < len(parents):
        b.next_page_token = encode_token({"i": i + 1})
    else:
        b.cursor_update["_reply_parents"] = None


_HANDLERS: dict[str, Callable[..., Awaitable[None]]] = {
    "workspace": _step_workspace, "users": _step_users, "channels": _step_channels,
    "members": _step_members, "history": _step_history, "replies": _step_replies,
}


# Writing
def write_batch(ws: str, step: str, batch: Batch) -> WriteResult:
    store = store_for(ws)
    changed: list[str] = []
    counts: dict[str, int] = {}
    entries: list[dict[str, Any]] = batch.extra.get("messages", [])
    created = apply_message_ops(store, entries, changed)
    if created:
        counts["SlackMessage"] = created
    result = write_generic(ws, batch, store=store)
    for k, v in counts.items():
        result.counts[k] = result.counts.get(k, 0) + v
    unlink = batch.extra.get("unlink_reactions") or []
    if unlink:
        store.delete_links("RELATED_TO_REACTION", "SlackMessage", "SlackReaction", [(a, c) for a, c in unlink])
    result.changed_ids = list(dict.fromkeys([*changed, *result.changed_ids]))
    return result


def apply_message_ops(store: GraphStore, entries: Sequence[Mapping[str, Any]], changed: list[str]) -> int:
    """Create new messages (never overwriting an existing one), version edits, update reply counts."""
    new_rows = [e["row"] for e in entries if e["op"] == "new"]
    n = 0
    if new_rows:
        have = existing_ids(store, "SlackMessage", [r["id"] for r in new_rows])
        fresh = [r for r in new_rows if r["id"] not in have]
        if fresh:
            n += store.upsert_nodes("SlackMessage", fresh)
            changed.extend(r["id"] for r in fresh)
    for e in entries:
        if e["op"] == "edit":
            if apply_edit(store, e["row"]):
                changed.append(e["row"]["id"])
                n += 1
        elif e["op"] == "touch":
            store.update_nodes("SlackMessage", [e["row"]])
    return n


def apply_edit(store: GraphStore, row: Mapping[str, Any]) -> bool:
    """Version the old text and apply the new one. Returns False when nothing changed (a retried write)."""
    current = store.get_node(row["id"])
    if current is None:
        store.upsert_nodes("SlackMessage", [dict(row)])
        return True
    if current.get("deleted"):
        return False
    if current.get("text") == row["text"] and current.get("editedAt") == row.get("editedAt"):
        return False
    props = {k: row[k] for k in ("text", "name", "editedAt", "replyCount", "permalink") if row.get(k) is not None}
    try:
        version_slack_message(store, row["id"], props)
    except NodeNotFound:  # deleted between the read and the write
        return False
    return True


# Live events (the Slack bot calls handle_message_event)
@dataclass
class EventOutcome:
    kind: str
    changed_ids: list[str] = field(default_factory=list)
    removed_links: list[dict[str, str]] = field(default_factory=list)
    version: int | None = None
    ignored: str | None = None


Enqueue = Callable[[str, list[str]], Awaitable[None]]


def _workspace_ctx(ws: str, workspace: Mapping[str, Any] | None) -> MsgCtx:
    if workspace is None:
        try:
            from actron.connectors.common import load_cursor

            workspace = load_cursor(ws, "slack").get("workspace") or {}
        except Exception as exc:  # no database: permalinks are simply left out
            log.warning("slack workspace info unavailable", extra={"error": str(exc)})
            workspace = {}
    return MsgCtx(workspace.get("domain"), workspace.get("bot_user_id"), workspace.get("id"))


async def handle_message_event(ws: str, event: Mapping[str, Any], *, workspace: Mapping[str, Any] | None = None,
                               enqueue: Enqueue | None = None) -> EventOutcome:
    """Apply one Slack Events API event (the inner `event` object) to the graph."""
    outcome = await asyncio.to_thread(_apply_event, ws, event, _workspace_ctx(ws, workspace))
    if outcome.kind == "deleted" and outcome.changed_ids:
        from actron.connectors.common import publish_ingestion_event

        await asyncio.to_thread(publish_ingestion_event, ws, "slack.message_deleted", {
            "messageId": outcome.changed_ids[0], "removedLinks": outcome.removed_links})
    if enqueue and outcome.kind in ("new", "edited") and outcome.changed_ids:
        await enqueue(ws, outcome.changed_ids)
    return outcome


def _apply_event(ws: str, event: Mapping[str, Any], ctx: MsgCtx) -> EventOutcome:
    store = store_for(ws)
    etype = event.get("type")
    subtype = event.get("subtype")
    if etype == "message":
        channel = event.get("channel")
        if not channel:
            return EventOutcome("ignored", ignored="no channel")
        if subtype == "message_changed":
            return _event_changed(store, channel, event, ctx)
        if subtype == "message_deleted":
            return _event_deleted(store, channel, event)
        if subtype in SKIPPED_SUBTYPES:
            return EventOutcome("ignored", ignored=str(subtype))
        return _event_new(store, channel, event, ctx)
    if etype == "channel_rename":
        ch = event.get("channel") or {}
        if ch.get("id"):
            store.update_nodes("SlackChannel", [{"id": ids.slack_channel(ch["id"]), "name": ch.get("name")}])
            return EventOutcome("renamed", [ids.slack_channel(ch["id"])])
    if etype == "member_joined_channel":
        user, channel = event.get("user"), event.get("channel")
        if user and channel:
            b = Batch(step="members")
            b.add_missing("SlackUser", {"id": ids.slack_user(user), "name": user})
            b.add_link("RELATED_TO_CHANNEL", "SlackUser", ids.slack_user(user), "SlackChannel",
                       ids.slack_channel(channel))
            write_generic(ws, b, store=store)
            return EventOutcome("joined", [ids.slack_user(user)])
    return EventOutcome("ignored", ignored=str(subtype or etype))


def _event_new(store: GraphStore, channel: str, event: Mapping[str, Any], ctx: MsgCtx) -> EventOutcome:
    b = Batch(step="events")
    plan_messages(store, b, channel, [event], ctx)
    entries = b.extra.get("messages", [])
    if not entries:
        return EventOutcome("ignored", ignored="duplicate or unchanged")
    changed: list[str] = []
    apply_message_ops(store, entries, changed)
    write_generic(store.workspace_id, b, store=store)
    return EventOutcome("new" if any(e["op"] == "new" for e in entries) else "edited", changed)


def _event_changed(store: GraphStore, channel: str, event: Mapping[str, Any], ctx: MsgCtx) -> EventOutcome:
    raw = dict(event.get("message") or {})
    if not raw.get("ts"):
        return EventOutcome("ignored", ignored="no message")
    raw.setdefault("edited", {"user": raw.get("user"), "ts": event.get("ts") or raw["ts"]})
    mid = ids.slack_msg(channel, str(raw["ts"]))
    b = Batch(step="events")
    row = message_row(channel, raw, ctx)
    message_extras(b, channel, raw, row, ctx)
    current = store.get_node(mid)
    if current is None:
        b.extra["messages"] = [{"op": "new", "row": row}]
    else:
        b.extra["messages"] = [{"op": "edit", "row": row}]
    changed: list[str] = []
    apply_message_ops(store, b.extra["messages"], changed)
    write_generic(store.workspace_id, b, store=store)
    node = store.get_node(mid)
    version = int(node["version"]) if node and node.get("version") else None
    return EventOutcome("edited" if changed else "ignored", changed, version=version,
                        ignored=None if changed else "text unchanged")


def tombstone_message(store: GraphStore, message_id: str, at: datetime | None = None) -> list[dict[str, str]]:
    """Tombstone a message and its outgoing reference links. Returns the links, for the audit record."""
    when = (at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    rows = store.query(
        "MATCH (m:SlackMessage {id: $id})-[r:MENTIONS|CONTAINS_REFERENCE]->(t) "
        "WHERE coalesce(r.deleted, false) = false "
        "SET r.deleted = true, r.deletedAt = $at RETURN type(r) AS rel, t.id AS target",
        {"id": message_id, "at": when})
    store.tombstone("SlackMessage", [message_id], at)
    return [{"rel": r["rel"], "target": r["target"]} for r in rows]


def _event_deleted(store: GraphStore, channel: str, event: Mapping[str, Any]) -> EventOutcome:
    ts = event.get("deleted_ts") or (event.get("previous_message") or {}).get("ts")
    if not ts:
        return EventOutcome("ignored", ignored="no deleted_ts")
    mid = ids.slack_msg(channel, str(ts))
    if store.get_node(mid) is None:
        return EventOutcome("ignored", ignored="message was never ingested")
    removed = tombstone_message(store, mid)
    return EventOutcome("deleted", [mid], removed_links=removed)
