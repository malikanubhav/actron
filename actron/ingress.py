"""Verified Slack HTTP transport and durable, single-consumer graph inbox."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import Request, urlopen

from actron.contracts import Payload, Rejected, Store, Unavailable, UnknownOutcome, digest


class Handler(Protocol):
    def handle(self, event: Payload) -> Payload: ...


class SlackAPI:
    """Minimal Slack Web API adapter; uncertain posts are never silently retried."""

    def __init__(
        self, token: str, endpoint: str = "https://slack.com/api", store: Store | None = None
    ) -> None:
        if not token:
            raise ValueError("SLACK_BOT_TOKEN is required")
        self.token = token
        self.store = store
        self.endpoint = endpoint.rstrip("/")

    def call(
        self, method: str, payload: Payload, *, write: bool = False, get: bool = False
    ) -> Payload:
        url = f"{self.endpoint}/{method}"
        if get:
            url += "?" + urlencode(payload)
        request = Request(
            url,
            data=None if get else json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                result: Payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            error = UnknownOutcome if write else Unavailable
            raise error(f"Slack {method} transport unavailable") from exc
        if not result.get("ok"):
            raise Unavailable(f"Slack {method}: {result.get('error', 'unknown_error')}")
        return result

    def start(self, channel: str, request_id: str, text: str) -> str:
        """Reconcile the durable root identity; an uncertain absent post is never retried."""
        if self.store is None:
            raise Unavailable("Slack root creation requires the durable store")
        journal = self.store.get("SlackRoot", request_id)
        if journal and journal.get("status") == "confirmed":
            return str(journal["thread"])
        client_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "actron-request:" + request_id))
        cursor, seen = "", set()
        for _ in range(100):
            arguments: Payload = {"channel": channel, "limit": 100, "include_all_metadata": "true"}
            if cursor:
                arguments["cursor"] = cursor
            page = self.call("conversations.history", arguments, get=True)
            for message in page.get("messages", []):
                metadata = message.get("metadata", {})
                matches = (
                    metadata.get("event_type") == "actron_request"
                    and metadata.get("event_payload", {}).get("request") == request_id
                )
                if message.get("client_msg_id") == client_id or matches:
                    thread = message.get("ts")
                    if not thread:
                        raise UnknownOutcome("Matching Slack root has no timestamp")
                    self.store.put(
                        "SlackRoot",
                        request_id,
                        {
                            "id": request_id,
                            "status": "confirmed",
                            "channel": channel,
                            "thread": str(thread),
                            "client_msg_id": client_id,
                        },
                    )
                    return str(thread)
            next_cursor = page.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                if page.get("has_more"):
                    raise Unavailable("Slack history incomplete without pagination cursor")
                break
            if next_cursor in seen:
                raise Unavailable("Slack history pagination did not advance")
            seen.add(next_cursor)
            cursor = next_cursor
        else:
            raise Unavailable("Slack root lookup exceeded bounded history; absence unproven")
        if journal:
            raise UnknownOutcome(
                "Slack root outcome remains unknown; reconcile visible message before retry"
            )
        self.store.put(
            "SlackRoot",
            request_id,
            {"id": request_id, "status": "unknown", "channel": channel, "client_msg_id": client_id},
        )
        result = self.call(
            "chat.postMessage",
            {
                "channel": channel,
                "text": text,
                "client_msg_id": client_id,
                "metadata": {
                    "event_type": "actron_request",
                    "event_payload": {"request": request_id},
                },
            },
            write=True,
        )
        if not result.get("ts"):
            raise UnknownOutcome("Slack root creation response omitted timestamp")
        thread = str(result["ts"])
        self.store.put(
            "SlackRoot",
            request_id,
            {
                "id": request_id,
                "status": "confirmed",
                "channel": channel,
                "thread": thread,
                "client_msg_id": client_id,
            },
        )
        return thread

    def post(
        self,
        channel: str,
        text: str,
        thread: str | None = None,
        blocks: list[Payload] | None = None,
    ) -> str:
        payload: Payload = {
            "channel": channel,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if thread:
            payload["thread_ts"] = thread
        if blocks:
            payload["blocks"] = blocks
        result = self.call("chat.postMessage", payload, write=True)
        if not result.get("ts"):
            raise UnknownOutcome("Slack post response missing timestamp")
        return str(result["ts"])


COMMAND_FIELDS: dict[str, set[str]] = {
    "request": {"project", "behavior", "repo", "base", "text"},
    "investigate": {"request", "project", "behavior", "repo", "base", "text"},
    "clarify": {"request", "text", "scope"},
    "revise": {"request", "text", "scope"},
    "execute": {"request"},
    "repair": {"request", "text"},
    "review": {"request", "text", "pr", "head", "scope"},
    "recover": {"request"},
    "status": {"request"},
}
BUTTON_FIELDS = {
    "approve": {"request", "revision", "hash"},
    "authorize_merge": {"request", "revision", "hash", "pr", "head"},
}


class SlackIngress:
    """Receive verifies raw bytes, validates a bounded schema, then durably enqueues.

    Run one dispatcher per graph. Slack retries reuse the authenticated event ID;
    pending/running records are replayed on restart through Workflow's idempotency.
    """

    def __init__(
        self,
        store: Store,
        workflow: Handler,
        signing_secret: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not signing_secret:
            raise ValueError("SLACK_SIGNING_SECRET is required")
        self.store, self.workflow = store, workflow
        self.secret = signing_secret.encode()
        self.clock = clock
        self._mutex = threading.Lock()
        self._dispatch = threading.Lock()

    def _verify(self, raw: bytes, headers: Mapping[str, str]) -> None:
        normalized = {key.lower(): value for key, value in headers.items()}
        stamp = normalized.get("x-slack-request-timestamp", "")
        try:
            timestamp = int(stamp)
        except ValueError as exc:
            raise Rejected("Missing Slack request timestamp") from exc
        if abs(self.clock() - timestamp) > 300:
            raise Rejected("Expired Slack request timestamp")
        expected = (
            "v0="
            + hmac.new(
                self.secret,
                b"v0:" + stamp.encode() + b":" + raw,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(expected, normalized.get("x-slack-signature", "")):
            raise Rejected("Invalid Slack signature")

    def _event(self, raw: bytes) -> Payload:
        try:
            form = parse_qs(raw.decode(), strict_parsing=True, max_num_fields=30)
            if any(len(values) != 1 for values in form.values()):
                raise ValueError("Repeated Slack form fields")
            if "payload" in form:
                payload = json.loads(form["payload"][0])
                if payload.get("type") != "block_actions" or len(payload.get("actions", [])) != 1:
                    raise ValueError("Expected one Slack button action")
                action = payload["actions"][0]
                verb = action["action_id"]
                if verb not in BUTTON_FIELDS or action.get("type") != "button":
                    raise ValueError("Unsupported Slack button")
                args = json.loads(action["value"])
                if not isinstance(args, dict) or set(args) != BUTTON_FIELDS[verb]:
                    raise ValueError("Button must bind the exact scope and current head")
                if not all(
                    isinstance(value, (str, int)) and not isinstance(value, bool) and str(value)
                    for value in args.values()
                ):
                    raise ValueError("Invalid button scope")
                channel, user = payload["channel"]["id"], payload["user"]["id"]
                identity = str(payload.get("trigger_id") or action["action_ts"])
                event = {**args, "type": verb, "interaction": True}
            else:
                if form.get("command") != ["/actron"]:
                    raise ValueError("Expected /actron command")
                text = form.get("text", [""])[0].strip()
                verb, _, data = text.partition(" ")
                if verb not in COMMAND_FIELDS:
                    raise ValueError("Unsupported command; approval requires a Slack button")
                args = json.loads(data or "{}")
                if not isinstance(args, dict) or not set(args) <= COMMAND_FIELDS[verb]:
                    raise ValueError("Unexpected command fields")
                for key, value in args.items():
                    if key == "scope":
                        if not isinstance(value, dict) or not set(value) <= {
                            "objective",
                            "acceptance",
                            "constraints",
                            "unresolved",
                            "membership",
                        }:
                            raise ValueError("Scope contains unsupported fields")
                        for scope_key, scope_value in value.items():
                            if scope_key in {"acceptance", "constraints", "unresolved"}:
                                if (
                                    not isinstance(scope_value, list)
                                    or len(scope_value) > 30
                                    or not all(
                                        isinstance(item, str) and 0 < len(item) <= 2000
                                        for item in scope_value
                                    )
                                ):
                                    raise ValueError("Scope criteria must be bounded string lists")
                            elif (
                                not isinstance(scope_value, str) or not 0 < len(scope_value) <= 2000
                            ):
                                raise ValueError(
                                    "Scope objective/membership must be bounded strings"
                                )
                    elif not isinstance(value, str) or not 0 < len(value) <= 12000:
                        raise ValueError("Command arguments must be nonempty strings")
                fresh = verb == "request" or (verb == "investigate" and "request" not in args)
                required = {"project", "behavior", "repo", "base"} if fresh else {"request"}
                if not required <= set(args):
                    raise ValueError("Missing command arguments")
                if verb in {"clarify", "review"} and "text" not in args:
                    raise ValueError("This command requires text")
                if verb == "revise" and not args.get("scope"):
                    raise ValueError("Revision requires inspectable scope")
                if verb == "review" and not {"pr", "head"} <= set(args):
                    raise ValueError("Review requires the current pr and head")
                channel, user = form["channel_id"][0], form["user_id"][0]
                identity = form["trigger_id"][0]
                event = {**args, "type": verb}
            if not all(isinstance(value, str) and value for value in (channel, user, identity)):
                raise ValueError("Missing Slack identity")
            # Only this authenticated transport can create these metadata fields.
            return {
                **event,
                "channel": channel,
                "user": user,
                "trusted_slack": True,
                "id": digest({"trigger": identity, "channel": channel, "user": user, "type": verb}),
            }
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise Rejected(f"Invalid Slack input: {exc}") from exc

    def receive(self, raw: bytes, headers: Mapping[str, str]) -> tuple[int, Payload]:
        if len(raw) > 65536:
            raise Rejected("Slack input exceeds 64 KiB")
        self._verify(raw, headers)
        event = self._event(raw)
        with self._mutex:
            if self.store.get("Inbox", event["id"]) is None:
                self.store.put(
                    "Inbox",
                    event["id"],
                    {
                        "id": event["id"],
                        "event": event,
                        "status": "pending",
                        "received": self.clock(),
                        "attempts": 0,
                    },
                )
        return 200, {"response_type": "ephemeral", "text": "Actron accepted this event."}

    def _handoffs(self) -> None:
        for handoff in self.store.list("Handoff"):
            if handoff.get("status") not in {"ready", "queued"}:
                continue
            state = self.store.get("Request", handoff["request"])
            if not state or state.get("phase") != "approved":
                continue
            if state.get("revision") != handoff.get("revision") or state.get("approval", {}).get(
                "id"
            ) != handoff.get("approval"):
                continue
            identifier = digest({"handoff": handoff["id"]})
            with self._mutex:
                if not self.store.get("Inbox", identifier):
                    event = {
                        "id": identifier,
                        "type": "execute",
                        "request": state["id"],
                        "channel": state["channel"],
                        "user": state["approval"]["user"],
                        "handoff": handoff["id"],
                    }
                    self.store.put(
                        "Inbox",
                        identifier,
                        {
                            "id": identifier,
                            "event": event,
                            "status": "pending",
                            "received": self.clock(),
                            "attempts": 0,
                        },
                    )
                if handoff["status"] == "ready":
                    self.store.put("Handoff", handoff["id"], {**handoff, "status": "queued"})

    def drain(self) -> int:
        processed = 0
        with self._dispatch:
            self._handoffs()
            queued = sorted(self.store.list("Inbox"), key=lambda row: row.get("received", 0))
            for row in queued:
                if row["status"] not in {"pending", "running"}:
                    continue
                if row.get("retry_after", 0) > self.clock():
                    continue
                row = {**row, "status": "running", "attempts": row.get("attempts", 0) + 1}
                self.store.put("Inbox", row["id"], row)
                try:
                    result = self.workflow.handle(row["event"])
                except Rejected as exc:
                    row.update(status="rejected", error=str(exc))
                except Exception as exc:  # noqa: BLE001 - durable boundary records unexpected provider errors
                    # The graph remains the audit source; no credentials/HTTP body are logged.
                    row.update(
                        status="pending",
                        error=type(exc).__name__,
                        retry_after=self.clock() + min(300, 2 ** min(row["attempts"], 8)),
                    )
                else:
                    if result.get("blocked"):
                        row.update(status="pending", result=result, retry_after=self.clock() + 5)
                    else:
                        row.update(status="done", result=result)
                self.store.put("Inbox", row["id"], row)
                processed += 1
            self._handoffs()
        return processed


def serve(ingress: SlackIngress, host: str = "127.0.0.1", port: int = 8080) -> None:
    """Serve /slack and /health; forwarding HTTPS is the deployment's responsibility."""
    stopped = threading.Event()

    class HTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return  # Raw paths and provider payloads do not belong in transport logs.

        def respond(self, status: int, body: Payload) -> None:
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if self.path != "/health":
                self.respond(404, {"error": "not_found"})
                return
            try:
                ingress.store.get("Health", "probe")
            except (Unavailable, OSError):
                self.respond(503, {"ready": False, "error": "graph_unavailable"})
            else:
                self.respond(200, {"ready": True})

        def do_POST(self) -> None:
            if self.path != "/slack":
                self.respond(404, {"error": "not_found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 65536:
                    raise Rejected("Invalid Slack body length")
                self.connection.settimeout(3)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise Rejected("Incomplete Slack body")
                status, body = ingress.receive(raw, dict(self.headers.items()))
            except Rejected as exc:
                self.respond(400, {"error": str(exc)})
            except (Unavailable, OSError, TimeoutError):
                self.respond(503, {"error": "Durable enqueue unavailable; Slack may retry"})
            else:
                self.respond(status, body)

    def dispatch() -> None:
        while not stopped.is_set():
            try:
                ingress.drain()
            except Exception as exc:  # noqa: BLE001 - keep inbox consumer alive during outages
                logging.getLogger(__name__).error("Inbox dispatch failed: %s", type(exc).__name__)
            stopped.wait(1)

    server = ThreadingHTTPServer((host, port), HTTPHandler)
    consumer = threading.Thread(target=dispatch, daemon=True, name="actron-dispatch")
    consumer.start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        stopped.set()
        server.server_close()
        consumer.join(timeout=25)
