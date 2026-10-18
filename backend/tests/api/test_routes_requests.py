"""Request routes (spec B, B.C7): success, auth failure, validation failure and 409 per route (B-AC-57)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from actron.flow import service
from actron.flow.approvals import publish_outcome
from tests.api._fixtures import FakeGateway, W6Env
from tests.api.conftest import Api


async def _new(api: Api, text: str = "Let project admins export invoices") -> dict[str, Any]:
    r = await api.post("/api/requests", {"text": text, "kindHint": "feature"})
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()["request"]
    return out


def _err(r: httpx.Response) -> str:
    return str(r.json()["error"]["code"])


async def test_create_and_get(api: Api, gateway: FakeGateway) -> None:
    """B-AC-57: POST /api/requests 201 with RequestDetail; GET returns it."""
    req = await _new(api)
    assert req["state"] == "Investigating" and req["source"] == "ui"
    r = await api.get(f"/api/requests/{req['id']}")
    assert r.status_code == 200 and r.json()["request"]["id"] == req["id"]
    assert r.headers.get("X-Request-ID")


async def test_create_validation_and_auth(api: Api, anon: httpx.AsyncClient) -> None:
    """B-AC-57: too short text -> 422 with the error shape; no session -> 401."""
    r = await api.post("/api/requests", {"text": "hi"})
    assert r.status_code == 422 and _err(r) == "invalid"
    assert r.json()["error"]["details"]["fields"][0]["field"] == "text"
    r = await anon.post("/api/requests", json={"text": "hello there"})
    assert r.status_code == 401 and _err(r) == "unauthenticated"


async def test_create_idempotent(api: Api, gateway: FakeGateway) -> None:
    """B-AC-2: the same Idempotency-Key on create returns the same request."""
    a = await api.post("/api/requests", {"text": "Add CSV export"}, key="create-1")
    b = await api.post("/api/requests", {"text": "Add CSV export"}, key="create-1")
    assert a.json()["request"]["id"] == b.json()["request"]["id"]
    assert len(gateway.started) == 1


async def test_ask_creates_question(api: Api) -> None:
    """B-AC-57: POST /api/ask creates a question-kind request."""
    r = await api.post("/api/ask", {"text": "Why are exports Finance-only?"})
    assert r.status_code == 201 and r.json()["request"]["kind"] == "question"


async def test_list_groups(api: Api, anon: httpx.AsyncClient) -> None:
    """B-AC-57: GET /api/requests with groups and counts; bad group -> 422; no session -> 401."""
    req = await _new(api)
    r = await api.get("/api/requests")
    assert r.status_code == 200 and r.json()["counts"]["running"] == 1
    assert r.json()["requests"][0]["id"] == req["id"]
    assert (await api.get("/api/requests?group=nope")).status_code == 422
    assert (await anon.get("/api/requests")).status_code == 401


async def test_get_unknown_404(api: Api, anon: httpx.AsyncClient) -> None:
    r = await api.get("/api/requests/req_missing")
    assert r.status_code == 404 and _err(r) == "not_found"
    assert (await anon.get("/api/requests/req_missing")).status_code == 401


async def test_other_workspace_request_invisible(api: Api, w6: W6Env) -> None:
    """B-AC-65: a request in another workspace is not found."""
    from actron.db import models as m
    from actron.db.session import session_scope

    req = await _new(api)
    with session_scope() as s:
        s.add(m.Workspace(id=w6.ws + "x", name="Other", graph_name=f"actron_{w6.ws}x", settings={}))
        s.flush()
        s.add(m.Membership(user_id=__import__("uuid").UUID(w6.owner_id), workspace_id=w6.ws + "x", role="owner"))
    from actron.api.deps import create_session

    token, _ = await create_session(w6.owner_id, w6.ws + "x")
    api.client.cookies.set("actron_session", token)
    assert (await api.get(f"/api/requests/{req['id']}")).status_code == 404


async def test_answers(api: Api, gateway: FakeGateway, anon: httpx.AsyncClient) -> None:
    """B-AC-57: answers: 200 in Needs your input, 409 elsewhere, 422 on a bad body, 401 without session."""
    req = await _new(api)
    r = await api.post(f"/api/requests/{req['id']}/answers", {"questionId": "q1", "value": "yes"})
    assert r.status_code == 409 and _err(r) == "invalid_transition"
    service.set_request_fields(req["id"], state="Needs your input")
    r = await api.post(f"/api/requests/{req['id']}/answers", {"questionId": "q1", "value": "yes"})
    assert r.status_code == 200 and r.json()["result"]["status"] == "accepted"
    assert (await api.post(f"/api/requests/{req['id']}/answers", {"questionId": "q1"})).status_code == 422
    assert (await anon.post(f"/api/requests/{req['id']}/answers", json={"questionId": "q1", "value": "x"})).status_code == 401


async def test_ticket_revision_post_and_list(api: Api, gateway: FakeGateway) -> None:
    """B-AC-57: revisions: 409 in the wrong state; accepted with the new revision; list with diffs."""
    req = await _new(api)
    body = {"content": {"objective": "Export for admins", "targetBranch": "main"}}
    r = await api.post(f"/api/requests/{req['id']}/ticket/revisions", body)
    assert r.status_code == 409
    assert (await api.post(f"/api/requests/{req['id']}/ticket/revisions", {"content": {}})).status_code == 422
    service.set_request_fields(req["id"], state="Awaiting approval")

    async def on_signal(rid: str, name: str, payload: dict[str, Any]) -> None:
        from actron.activities.request import save_revision

        rev = await save_revision({"ws": api.env.ws, "requestId": rid, "content": payload["content"],
                                   "createdBy": "Owner"})
        await publish_outcome(rid, payload["idempotencyKey"], {"status": "accepted", "reason": None,
                                                          "revision": rev, "state": "Awaiting approval"})

    gateway.on_signal = on_signal
    r = await api.post(f"/api/requests/{req['id']}/ticket/revisions", body)
    assert r.status_code == 200, r.text
    assert r.json()["revision"]["n"] == 1 and len(r.json()["revision"]["hash"]) == 64
    body2 = {"content": {"objective": "Export for admins and owners", "targetBranch": "main"}}
    await api.post(f"/api/requests/{req['id']}/ticket/revisions", body2)
    r = await api.get(f"/api/requests/{req['id']}/ticket/revisions")
    data = r.json()
    assert [x["n"] for x in data["revisions"]] == [1, 2]
    assert data["diffs"] == [{"from": 1, "to": 2, "changes": [{"field": "objective",
                                                               "before": "Export for admins",
                                                               "after": "Export for admins and owners"}]}]


@pytest.mark.parametrize(("status", "reason", "code"), [
    ("accepted", None, 200), ("refused", "stale_revision", 409), ("refused", "external_edit", 409)])
async def test_approvals_status_mapping(api: Api, gateway: FakeGateway, status: str, reason: str | None,
                                        code: int) -> None:
    """B-AC-57 / B.C7: approvals answer 200 accepted, 409 with the refusal reason."""
    req = await _new(api)
    service.set_request_fields(req["id"], state="Awaiting approval")

    async def on_signal(rid: str, name: str, payload: dict[str, Any]) -> None:
        await publish_outcome(rid, payload["idempotencyKey"], {"status": status, "reason": reason, "state": "Building"})

    gateway.on_signal = on_signal
    r = await api.post(f"/api/requests/{req['id']}/approvals", {"kind": "ticket", "revisionHash": "a" * 64})
    assert r.status_code == code
    if code == 409:
        assert _err(r) == reason and r.json()["error"]["details"]["result"]["status"] == "refused"
    else:
        assert r.json()["result"]["status"] == "accepted"


async def test_approval_pending_202(api: Api, gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch) -> None:
    """B.C7: no decision within the wait -> 202 pending."""
    monkeypatch.setattr(service, "OUTCOME_WAIT_S", 0.1)
    req = await _new(api)
    service.set_request_fields(req["id"], state="Awaiting approval")
    r = await api.post(f"/api/requests/{req['id']}/approvals", {"kind": "ticket", "revisionHash": "b" * 64})
    assert r.status_code == 202 and r.json()["result"]["status"] == "pending"


async def test_approval_validation(api: Api) -> None:
    req = await _new(api)
    r = await api.post(f"/api/requests/{req['id']}/approvals", {"kind": "ticket"})
    assert r.status_code == 422
    r = await api.post(f"/api/requests/{req['id']}/approvals", {"kind": "merge", "headSha": "x"})
    assert r.status_code == 422


async def test_approval_not_an_approver_403(app: Any, api: Api, w6: W6Env, gateway: FakeGateway) -> None:
    """B-AC-84 / B.C7: a member who is not an approver gets 403 not_an_approver."""
    from tests.api.conftest import signed_in

    req = await _new(api)
    service.set_request_fields(req["id"], state="Awaiting approval")
    member = await signed_in(app, w6, w6.add_user("Member"))
    r = await member.post(f"/api/requests/{req['id']}/approvals", {"kind": "ticket", "revisionHash": "c" * 64})
    await member.client.aclose()
    assert r.status_code == 403 and _err(r) == "not_an_approver"


@pytest.mark.parametrize(("path", "body", "state"), [
    ("feedback", {"text": "Rename it", "headSha": "abc"}, "PR ready for review"),
    ("cancel", {"reason": "no longer needed"}, "Investigating"),
    ("retry", None, "Needs attention"),
    ("close-pr", {"reason": "not now"}, "PR ready for review"),
])
async def test_actions_success_and_409(api: Api, gateway: FakeGateway, path: str, body: Any, state: str) -> None:
    """B-AC-57: feedback, cancel, retry, close-pr: 409 in the wrong state, 200 in the right one."""
    req = await _new(api)
    service.set_request_fields(req["id"], state="Done")
    r = await api.post(f"/api/requests/{req['id']}/{path}", body)
    assert r.status_code == 409 and _err(r) == "invalid_transition"
    service.set_request_fields(req["id"], state=state)
    r = await api.post(f"/api/requests/{req['id']}/{path}", body)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["status"] == "accepted"


async def test_feedback_validation(api: Api) -> None:
    req = await _new(api)
    assert (await api.post(f"/api/requests/{req['id']}/feedback", {"text": ""})).status_code == 422


async def test_pr_diff_without_pr_404(api: Api) -> None:
    req = await _new(api)
    r = await api.get(f"/api/requests/{req['id']}/pr/diff")
    assert r.status_code == 404 and _err(r) == "no_pr"


async def test_build_log(api: Api, tmp_path: Any) -> None:
    """B.C7: build log as text/plain; unknown build -> 404; secrets are redacted."""
    from datetime import UTC, datetime

    from actron.config import get_settings
    from actron.db import models as m
    from actron.db.session import session_scope

    req = await _new(api)
    log_file = tmp_path / "build.log"
    secret = get_settings().SESSION_SECRET or "sess-secret-value"
    log_file.write_text(f"step one\nusing {secret}\n")
    with session_scope() as s:
        s.add(m.BuildRun(id="bld_1", request_id=req["id"], status="passed", branch="b", base_sha="x",
                         started_at=datetime.now(UTC), log_path=str(log_file)))
    r = await api.get(f"/api/requests/{req['id']}/builds/bld_1/log")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "step one" in r.text
    if get_settings().SESSION_SECRET:
        assert secret not in r.text
    assert (await api.get(f"/api/requests/{req['id']}/builds/nope/log")).status_code == 404


async def test_build_log_from_the_build_folder(api: Api, tmp_path: Any) -> None:
    """B.C7: a build folder (what record_build_result stores) reads as every Pi attempt in order."""
    from datetime import UTC, datetime

    from actron.db import models as m
    from actron.db.session import session_scope

    req = await _new(api)
    folder = tmp_path / "bld_2"
    folder.mkdir()
    (folder / "pi-attempt-2.jsonl").write_text('{"type": "agent_start", "n": 2}\n')
    (folder / "pi-attempt-1.jsonl").write_text('{"text": "FAILED tests/test_ops.py::test_subtract"}\n')
    (folder / "pi-attempt-1.stderr").write_text("")
    (folder / "pi-attempt-10.jsonl").write_text('{"n": 10}\n')
    with session_scope() as s:
        s.add(m.BuildRun(id="bld_2", request_id=req["id"], status="passed", branch="b", base_sha="x",
                         started_at=datetime.now(UTC), log_path=str(folder)))
    text = (await api.get(f"/api/requests/{req['id']}/builds/bld_2/log")).text
    assert text.index("pi-attempt-1.jsonl") < text.index("pi-attempt-2.jsonl") < text.index("pi-attempt-10.jsonl")
    assert "test_subtract" in text and "pi-attempt-1.stderr" not in text


async def test_request_events_sse(app: Any, api: Api) -> None:
    """B-AC-4: the SSE route replays from Last-Event-ID with `id: seq` and `event: type` (real HTTP server)."""
    import asyncio
    import socket

    import uvicorn

    from actron.flow.events import emit

    req = await _new(api)
    for i in range(3):
        await emit(api.env.ws, req["id"], "build.step", {"text": f"s{i}"})
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    lines: list[str] = []

    async def read() -> None:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", cookies=api.client.cookies) as c, \
                c.stream("GET", f"/api/requests/{req['id']}/events", headers={"Last-Event-ID": "2"}) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                lines.append(line.rstrip("\r"))
                if sum(1 for x in lines if x.startswith("id:")) >= 2:
                    return

    try:
        await asyncio.wait_for(read(), 10)
    finally:
        server.should_exit = True
        await task
    assert [x for x in lines if x.startswith("id:")] == ["id: 3", "id: 4"]
    assert "event: build.step" in lines


async def test_sse_streams_send_a_comment_at_once(app: Any, api: Api) -> None:
    """B-AC-4 and C-AC-17: both streams send an SSE comment as soon as they open, before any event or heartbeat,
    so proxies flush the headers and the browser reports the stream live."""
    import asyncio
    import socket
    import time

    import uvicorn

    req = await _new(api)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async def first_line(path: str) -> tuple[str, float]:
        start = time.monotonic()
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", cookies=api.client.cookies) as c, \
                c.stream("GET", path, headers={"Last-Event-ID": "999999"}) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.strip():
                    return line.rstrip("\r"), time.monotonic() - start
        return "", time.monotonic() - start

    try:
        for path in ("/api/stream", f"/api/requests/{req['id']}/events"):
            line, took = await asyncio.wait_for(first_line(path), 10)
            assert line == ": connected", (path, line)
            assert took < 5, (path, took)  # the heartbeat comes after 15 s
    finally:
        server.should_exit = True
        await task


async def test_events_unknown_request_404(api: Api) -> None:
    assert (await api.get("/api/requests/req_nope/events")).status_code == 404
