"""Slack bot: Bolt for Python (async) handlers for /actron, mentions, buttons, the request-changes modal,
thread replies, channel messages and uninstall events (spec B, B11, B11a; PROMPT 8.9).

Every handler acknowledges first, then hands the work to an asyncio task that calls actron.flow.service
through the adapter in slack_common. Redis idempotency guards event_id and trigger_id + action_id.
HTTP mode: `mount(app)` adds /slack/events, /slack/commands and /slack/interactions with signature
verification done by Bolt (bad signature or a timestamp older than five minutes gets 401).
Socket Mode: `await run_socket_mode()` from the worker when an app-level token exists.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import re
from collections.abc import Coroutine
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_bolt.authorization import AuthorizeResult
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from actron.config import get_settings
from actron.db.models import Connection, Membership, User
from actron.db.models import Request as RequestRow
from actron.db.session import async_session
from actron.integrations import slack_blocks as sb
from actron.integrations import slack_sender
from actron.integrations.slack_common import (
    COMMANDS_PATH,
    EVENTS_PATH,
    INTERACTIONS_PATH,
    claim,
    credentials_for_team,
    get_service,
    log,
    secret_dict,
    web_client,
    workspace_for_team,
)
from actron.integrations.slack_oauth import disconnect_team

ACTION_PATTERN = re.compile(
    r"^(answer|approve_ticket|approve_pr|request_changes|close_pr|retry|open):"
)
NUMBERED_REPLY = re.compile(
    r"^\s*(?:q(?:uestion)?\s*)?#?(\d{1,2})\s*[.):\-]?\s+(.+)$", re.IGNORECASE | re.DOTALL
)
MENTION = re.compile(r"<@[A-Z0-9]+>")
NOT_SET_UP = (
    "Actron is not connected to this Slack workspace yet. Connect Slack in Actron, then try again."
)
START_FAILED = "Actron could not start this request. Try again, or open Actron."

_TASKS: set[asyncio.Task[None]] = set()


# ---------------------------------------------------------------- background work


def spawn(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    """Run work after the acknowledgement. Errors are logged, never lost silently."""

    async def guarded() -> None:
        try:
            await coro
        except Exception:
            log.warning("slack handler failed", exc_info=True)

    task = asyncio.get_running_loop().create_task(guarded())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


async def drain() -> None:
    """Wait for all handed-off work (tests and graceful shutdown).

    Waits only on unfinished tasks: awaiting a gather of tasks that are already done does not yield to the
    event loop, so the done callbacks that remove them from _TASKS would never run and the loop would spin.
    """
    while True:
        pending = [t for t in _TASKS if not t.done()]
        if not pending:
            _TASKS.difference_update([t for t in list(_TASKS) if t.done()])
            return
        await asyncio.gather(*pending, return_exceptions=True)


# ---------------------------------------------------------------- authorization


_fallback_ids: dict[str, tuple[str | None, str | None]] = {}


async def authorize(
    enterprise_id: str | None, team_id: str | None, user_id: str | None = None
) -> AuthorizeResult | None:
    """Bot token for the incoming team from the stored installation (B-AC-90); SLACK_BOT_TOKEN is the dev fallback."""
    creds = await credentials_for_team(team_id)
    if creds is not None:
        return AuthorizeResult(
            enterprise_id=enterprise_id,
            team_id=team_id,
            bot_token=creds.token,
            bot_id=creds.bot_id,
            bot_user_id=creds.bot_user_id,
            user_id=user_id,
        )
    token = get_settings().SLACK_BOT_TOKEN
    if not token:
        return None
    if token not in _fallback_ids:
        try:
            who = await web_client(token).auth_test()
            _fallback_ids[token] = (who.get("bot_id"), who.get("user_id"))
        except Exception:
            _fallback_ids[token] = (None, None)
    bot_id, bot_user_id = _fallback_ids[token]
    return AuthorizeResult(
        enterprise_id=enterprise_id,
        team_id=team_id,
        bot_token=token,
        bot_id=bot_id,
        bot_user_id=bot_user_id,
        user_id=user_id,
    )


# ---------------------------------------------------------------- identity


def team_of(body: dict[str, Any]) -> str | None:
    event = body.get("event") or {}
    return (
        body.get("team_id")
        or (body.get("team") or {}).get("id")
        or (body.get("user") or {}).get("team_id")
        or event.get("team")
        or None
    )


async def actor_for(
    ws: str, slack_user_id: str, client: AsyncWebClient | None = None
) -> dict[str, Any]:
    """The Actron user for a Slack user id, created on first contact (spec B, B11 identity)."""
    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.slack_user_id == slack_user_id))
        ).scalar_one_or_none()
    if user is None:
        name, email = slack_user_id, None
        if client is not None:
            try:
                info = await client.users_info(user=slack_user_id)
                u = info.get("user") or {}
                profile = u.get("profile") or {}
                name = profile.get("display_name") or u.get("real_name") or name
                email = profile.get("email")
            except SlackApiError:
                log.info("users.info failed for %s", slack_user_id)
        try:
            async with async_session() as session:
                session.add(User(slack_user_id=slack_user_id, name=str(name), email=email))
        except IntegrityError:
            pass  # another delivery created it first
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.slack_user_id == slack_user_id))
            ).scalar_one()
    async with async_session() as session:
        member = (
            await session.execute(
                select(Membership).where(
                    Membership.user_id == user.id, Membership.workspace_id == ws
                )
            )
        ).scalar_one_or_none()
        if member is None:
            try:
                session.add(Membership(user_id=user.id, workspace_id=ws, role="member"))
                await session.flush()
            except IntegrityError:
                await session.rollback()
    return {
        "userId": str(user.id),
        "slackUserId": slack_user_id,
        "surface": "slack",
        "name": user.name,
    }


# ---------------------------------------------------------------- starting requests


async def _thread_say(client: AsyncWebClient, channel: str, thread_ts: str, text: str) -> None:
    try:
        await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
    except SlackApiError:
        log.info("could not post in thread", exc_info=True)


async def start_request(
    ws: str,
    client: AsyncWebClient,
    *,
    channel: str,
    thread_ts: str,
    user: str,
    text: str,
    kind_hint: str | None,
    key: str,
) -> None:
    actor = await actor_for(ws, user, client)
    try:
        view = await get_service().create_request(
            ws,
            text=text,
            kind_hint=kind_hint,
            actor=actor,
            slack={"channel": channel, "threadTs": thread_ts},
            idempotency_key=key,
        )
    except Exception:
        log.warning("create_request failed", exc_info=True)
        await _thread_say(client, channel, thread_ts, START_FAILED)
        return
    await slack_sender.post_acknowledgement(ws, view)


def split_ask(text: str) -> tuple[str, str | None]:
    """`ask <question>` starts Q&A mode (B14)."""
    m = re.match(r"^ask\s+(.+)$", text.strip(), re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip(), "question") if m else (text.strip(), None)


async def handle_command(body: dict[str, Any], client: AsyncWebClient, respond: Any) -> None:
    if not await claim(f"cmd:{body.get('trigger_id')}"):
        return
    raw = (body.get("text") or "").strip()
    text, kind = split_ask(raw)
    if not text or raw.lower() == "ask":
        await respond(text=sb.USAGE_TEXT, response_type="ephemeral")
        return
    ws = await workspace_for_team(team_of(body))
    if ws is None:
        await respond(text=NOT_SET_UP, response_type="ephemeral")
        return
    channel, user = body["channel_id"], body["user_id"]
    try:
        root = await client.chat_postMessage(
            channel=channel, text=f"<@{user}> asked Actron: {sb.esc(sb.one_line(text, 200))}"
        )
    except SlackApiError as exc:
        if exc.response.get("error") in ("not_in_channel", "channel_not_found"):
            await respond(
                text="Invite Actron to this channel first with /invite @Actron, then try again.",
                response_type="ephemeral",
            )
            return
        raise
    await start_request(
        ws,
        client,
        channel=channel,
        thread_ts=str(root["ts"]),
        user=user,
        text=text,
        kind_hint=kind,
        key=f"slack:cmd:{body.get('trigger_id')}",
    )


async def handle_mention(body: dict[str, Any], client: AsyncWebClient) -> None:
    event = body["event"]
    if not await claim(f"evt:{body.get('event_id')}"):
        return
    ws = await workspace_for_team(team_of(body))
    channel, thread_ts = event["channel"], event.get("thread_ts") or event["ts"]
    if ws is None:
        await _thread_say(client, channel, thread_ts, NOT_SET_UP)
        return
    text, kind = split_ask(MENTION.sub("", event.get("text", "")).strip())
    if not text:
        await _thread_say(client, channel, thread_ts, sb.USAGE_TEXT.replace("/actron", "@Actron"))
        return
    await start_request(
        ws,
        client,
        channel=channel,
        thread_ts=thread_ts,
        user=event["user"],
        text=text,
        kind_hint=kind,
        key=f"slack:evt:{body.get('event_id')}",
    )


# ---------------------------------------------------------------- buttons


async def _tell(client: AsyncWebClient, body: dict[str, Any], text: str) -> None:
    user = (body.get("user") or {}).get("id")
    channel = (body.get("channel") or {}).get("id") or (body.get("container") or {}).get(
        "channel_id"
    )
    try:
        if channel and user:
            await client.chat_postEphemeral(channel=channel, user=user, text=text)
        elif user:
            opened = await client.conversations_open(users=user)
            await client.chat_postMessage(channel=opened["channel"]["id"], text=text)
    except SlackApiError:
        log.info("could not tell the user", exc_info=True)


async def _option_by_index(ws: str, rid: str, qid: str, index: int) -> str | None:
    view = await get_service().get_request_view(ws, rid)
    for q in view.get("questions") or []:
        if q["questionId"] == qid and 0 <= index < len(q.get("options") or []):
            return str(q["options"][index]["value"])
    return None


async def handle_action(
    body: dict[str, Any], action: dict[str, Any], client: AsyncWebClient
) -> None:
    aid = str(action["action_id"])
    trigger = body.get("trigger_id")
    if not await claim(f"act:{trigger}:{aid}"):
        return
    ws = await workspace_for_team(team_of(body))
    if ws is None:
        await _tell(client, body, NOT_SET_UP)
        return
    user = body["user"]["id"]
    actor = await actor_for(ws, user, client)
    key = f"slack:{trigger}:{aid}"
    kind, _, rest = aid.partition(":")
    svc = get_service()
    try:
        if kind == "answer":
            rid, qid, value = rest.split(":", 2)
            if value == "~select":
                value = str((action.get("selected_option") or {}).get("value", ""))
            elif value.startswith("#") and value[1:].isdigit():
                value = await _option_by_index(ws, rid, qid, int(value[1:])) or value
            result = await svc.answer(
                ws, rid, question_id=qid, value=value, actor=actor, idempotency_key=key
            )
        elif kind == "approve_ticket":
            rid, digest = rest.split(":", 1)
            result = await svc.approve(
                ws,
                rid,
                kind="ticket",
                revision_hash=digest,
                head_sha=None,
                actor=actor,
                idempotency_key=key,
            )
        elif kind == "approve_pr":
            rid, sha = rest.split(":", 1)
            result = await svc.approve(
                ws,
                rid,
                kind="pr",
                revision_hash=None,
                head_sha=sha,
                actor=actor,
                idempotency_key=key,
            )
        elif kind == "close_pr":
            result = await svc.close_pr(
                ws, rest, reason="Closed from Slack.", actor=actor, idempotency_key=key
            )
        elif kind == "retry":
            result = await svc.retry(ws, rest, actor=actor, idempotency_key=key)
        else:
            return
    except Exception:
        log.warning("service call failed for %s", kind, exc_info=True)
        await _tell(client, body, sb.refusal_text(None))
        return
    if result.get("status") == "refused":
        await _tell(client, body, sb.refusal_text(result.get("reason")))


async def open_changes_modal(body: dict[str, Any], rid: str, client: AsyncWebClient) -> None:
    try:
        await client.views_open(trigger_id=body["trigger_id"], view=sb.request_changes_modal(rid))
    except SlackApiError:
        log.warning("views.open failed", exc_info=True)


async def handle_changes_submission(body: dict[str, Any], client: AsyncWebClient) -> None:
    view = body["view"]
    if not await claim(f"view:{view.get('id')}:{body.get('trigger_id')}"):
        return
    rid, text = str(view["private_metadata"]), _modal_text(view)
    ws = await workspace_for_team(team_of(body))
    if ws is None:
        await _tell(client, body, NOT_SET_UP)
        return
    actor = await actor_for(ws, body["user"]["id"], client)
    await _send_feedback(ws, rid, text, actor, client, body, key=f"slack:view:{view.get('id')}")


def _modal_text(view: dict[str, Any]) -> str:
    try:
        return str(view["state"]["values"]["feedback"]["text"]["value"] or "").strip()
    except (KeyError, TypeError):
        return ""


async def _send_feedback(
    ws: str,
    rid: str,
    text: str,
    actor: dict[str, Any],
    client: AsyncWebClient,
    body: dict[str, Any],
    *,
    key: str,
) -> None:
    svc = get_service()
    try:
        current = await svc.get_request_view(ws, rid)
        head = (current.get("pr") or {}).get("headSha")
        result = await svc.feedback(
            ws, rid, text=text, head_sha=head, actor=actor, idempotency_key=key
        )
    except Exception:
        log.warning("feedback failed", exc_info=True)
        await _tell(client, body, sb.refusal_text(None))
        return
    if result.get("status") == "refused":
        await _tell(client, body, sb.refusal_text(result.get("reason")))


# ---------------------------------------------------------------- messages and thread replies


async def allowed_channels(ws: str) -> set[str]:
    """Channels chosen in the Slack connection; SLACK_CHANNELS is the development fallback."""
    async with async_session() as session:
        conn = (
            await session.execute(
                select(Connection).where(
                    Connection.workspace_id == ws, Connection.provider == "slack"
                )
            )
        ).scalar_one_or_none()
    chosen = (conn.config or {}).get("channels") if conn else None
    if chosen:
        return {str(c) for c in chosen}
    env = get_settings().SLACK_CHANNELS or ""
    return {c.strip() for c in env.split(",") if c.strip()}


async def feed_ingestion(ws: str, event: dict[str, Any]) -> None:
    """Hand a channel message to W3's live ingestion (imported lazily; it may not exist yet)."""
    try:
        handler = importlib.import_module("actron.connectors.slack").handle_message_event
    except (ImportError, AttributeError):
        log.info("actron.connectors.slack.handle_message_event is not available yet")
        return
    result = handler(ws, event)
    if inspect.isawaitable(result):
        await result


async def request_in_thread(ws: str, channel: str, thread_ts: str) -> str | None:
    async with async_session() as session:
        rid = (
            await session.execute(
                select(RequestRow.id).where(
                    RequestRow.workspace_id == ws,
                    RequestRow.slack_channel == channel,
                    RequestRow.slack_thread_ts == thread_ts,
                )
            )
        ).scalar_one_or_none()
    return None if rid is None else str(rid)


async def handle_thread_reply(
    ws: str, rid: str, event: dict[str, Any], client: AsyncWebClient, body: dict[str, Any]
) -> None:
    text = (event.get("text") or "").strip()
    user = event.get("user")
    if not text or not user:
        return
    key = f"slack:evt:{body.get('event_id')}"
    actor = await actor_for(ws, user, client)
    if text.lower().startswith("feedback:"):
        await _send_feedback(
            ws, rid, text[len("feedback:") :].strip(), actor, client, _reply_body(event), key=key
        )
        return
    m = NUMBERED_REPLY.match(text)
    if not m:
        return  # ordinary conversation in the thread
    number, answer_text = int(m.group(1)), m.group(2).strip()
    svc = get_service()
    view = await svc.get_request_view(ws, rid)
    questions = view.get("questions") or []
    if not 1 <= number <= len(questions):
        return
    q = questions[number - 1]
    value = answer_text
    if q.get("kind") != "text":
        matched = next(
            (
                str(o["value"])
                for o in q.get("options") or []
                if answer_text.lower() in (str(o["value"]).lower(), str(o.get("label", "")).lower())
            ),
            None,
        )
        if matched is None:
            await _tell(
                client,
                _reply_body(event),
                "Use the buttons for that question, or reply with one of its options.",
            )
            return
        value = matched
    result = await svc.answer(
        ws, rid, question_id=q["questionId"], value=value, actor=actor, idempotency_key=key
    )
    if result.get("status") == "refused":
        await _tell(client, _reply_body(event), sb.refusal_text(result.get("reason")))


def _reply_body(event: dict[str, Any]) -> dict[str, Any]:
    return {"user": {"id": event.get("user")}, "channel": {"id": event.get("channel")}}


async def handle_message(body: dict[str, Any], client: AsyncWebClient) -> None:
    event = body["event"]
    if not await claim(f"evt:{body.get('event_id')}"):
        return
    ws = await workspace_for_team(team_of(body))
    if ws is None:
        return
    channel = event.get("channel")
    human = not event.get("bot_id") and event.get("subtype") in (None, "thread_broadcast")
    thread_ts = event.get("thread_ts")
    if human and thread_ts and thread_ts != event.get("ts") and channel:
        rid = await request_in_thread(ws, channel, thread_ts)
        if rid:
            await handle_thread_reply(ws, rid, event, client, body)
    if channel and channel in await allowed_channels(ws):
        await feed_ingestion(ws, event)


async def handle_uninstall(body: dict[str, Any]) -> None:
    event = body.get("event") or {}
    if event.get("type") == "tokens_revoked" and not (event.get("tokens") or {}).get("bot"):
        return  # only user tokens were revoked
    if not await claim(f"evt:{body.get('event_id')}"):
        return
    await disconnect_team(team_of(body), reason=str(event.get("type")))


# ---------------------------------------------------------------- app


def _register(app: AsyncApp) -> None:
    @app.command("/actron")
    async def on_command(
        ack: Any, body: dict[str, Any], client: AsyncWebClient, respond: Any
    ) -> None:
        await ack()
        spawn(handle_command(body, client, respond))

    @app.event("app_mention")
    async def on_mention(body: dict[str, Any], client: AsyncWebClient) -> None:
        if (body.get("event") or {}).get("bot_id"):
            return
        spawn(handle_mention(body, client))

    @app.action(ACTION_PATTERN)
    async def on_action(
        ack: Any, body: dict[str, Any], action: dict[str, Any], client: AsyncWebClient
    ) -> None:
        await ack()
        aid = str(action["action_id"])
        if aid.startswith("open:"):
            return  # URL buttons: Slack opens the link itself
        if aid.startswith("request_changes:"):
            if await claim(f"act:{body.get('trigger_id')}:{aid}"):
                await open_changes_modal(body, aid.split(":", 1)[1], client)
            return
        spawn(handle_action(body, action, client))

    @app.view("request_changes")
    async def on_submit(ack: Any, body: dict[str, Any], client: AsyncWebClient) -> None:
        if not _modal_text(body["view"]):
            await ack(response_action="errors", errors={"feedback": "Write what should change."})
            return
        await ack()
        spawn(handle_changes_submission(body, client))

    @app.event("message")
    async def on_message(body: dict[str, Any], client: AsyncWebClient) -> None:
        spawn(handle_message(body, client))

    @app.event("app_uninstalled")
    async def on_uninstalled(body: dict[str, Any]) -> None:
        spawn(handle_uninstall(body))

    @app.event("tokens_revoked")
    async def on_revoked(body: dict[str, Any]) -> None:
        spawn(handle_uninstall(body))

    for name in ("member_joined_channel", "channel_rename"):
        # Subscribed in the manifest for ingestion; nothing to do in the bot.
        app.event(name)(_ignore)


async def _ignore() -> None:
    return None


def create_app(*, signing_secret: str | None = None, socket_mode: bool = False) -> AsyncApp:
    s = get_settings()
    secret = signing_secret or s.SLACK_SIGNING_SECRET
    app = AsyncApp(
        signing_secret=secret,
        authorize=authorize,  # type: ignore[arg-type]
        client=AsyncWebClient(base_url=s.SLACK_API_URL),
        request_verification_enabled=not socket_mode,
    )
    _register(app)
    return app


_apps: dict[str, AsyncApp] = {}


def get_app(*, socket_mode: bool = False) -> AsyncApp:
    key = "socket" if socket_mode else "http"
    if key not in _apps:
        _apps[key] = create_app(socket_mode=socket_mode)
    return _apps[key]


def reset_apps() -> None:
    """Tests: forget cached apps after settings change."""
    _apps.clear()


def mount(app: FastAPI, bolt_app: AsyncApp | None = None) -> None:
    """HTTP mode: add the three Slack routes to FastAPI (spec B, B11)."""
    handlers: dict[str, AsyncSlackRequestHandler] = {}

    async def endpoint(request: Request) -> Response:
        if "h" not in handlers:
            if bolt_app is None and not get_settings().SLACK_SIGNING_SECRET:
                return JSONResponse(
                    {
                        "error": {
                            "code": "slack_not_configured",
                            "message": "SLACK_SIGNING_SECRET is not set.",
                        }
                    },
                    status_code=503,
                )
            handlers["h"] = AsyncSlackRequestHandler(bolt_app or get_app())
        return await handlers["h"].handle(request)

    for path in (EVENTS_PATH, COMMANDS_PATH, INTERACTIONS_PATH):
        app.add_api_route(path, endpoint, methods=["POST"], include_in_schema=False)


async def app_token() -> str | None:
    """App-level token for Socket Mode: the connection's, else SLACK_APP_TOKEN."""
    async with async_session() as session:
        conns = (
            (await session.execute(select(Connection).where(Connection.provider == "slack")))
            .scalars()
            .all()
        )
    for conn in conns:
        token = secret_dict(conn.secret_encrypted).get("app_token")
        if token and conn.status == "connected":
            return str(token)
    return get_settings().SLACK_APP_TOKEN


async def run_socket_mode() -> None:
    """Run until cancelled. Returns at once when no app-level token exists (HTTP mode is used instead)."""
    token = await app_token()
    if not token:
        log.info("no slack app-level token; socket mode not started")
        return
    handler = AsyncSocketModeHandler(
        get_app(socket_mode=True),
        token,
        web_client=AsyncWebClient(token=token, base_url=get_settings().SLACK_API_URL),
    )
    try:
        await handler.start_async()  # type: ignore[no-untyped-call]
    finally:
        await handler.close_async()  # type: ignore[no-untyped-call]
