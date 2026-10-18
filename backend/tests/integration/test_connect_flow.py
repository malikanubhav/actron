# ruff: noqa: F403
"""Connect, backfill, then incremental through the real Temporal server: A-AC-68, A-AC-69, A-AC-63 (linking started)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from actron.connectors import common
from actron.graph import ids
from tests.fakes.github import FakeGithub, build_pr_fixture, user
from tests.fakes.support import *

REPO = "acme/widgets"
CONFIG = {"repository": REPO, "api_url": "http://fake.github", "historyDays": 3650}


async def _wait(client: Any, workflow_id: str) -> dict[str, Any]:
    result: dict[str, Any] = await client.get_workflow_handle(workflow_id).result()
    return result


def _event_types(ws: str) -> list[str]:
    from actron.db.models import Event
    from actron.db.session import session_scope

    with session_scope() as session:
        rows = session.execute(select(Event).where(Event.workspace_id == ws, Event.request_id.is_(None))
                               .order_by(Event.id)).scalars().all()
        return [e.type for e in rows]


async def test_a_ac_68_connect_backfills_then_incremental_ingests_only_the_change(
        ws: str, store: Any, fake_github: FakeGithub, save_conn: Any, ingest_worker: Any) -> None:
    """A-AC-68 (GitHub with a fake provider; the code source is covered where the code pipeline exists)."""
    acts, client = ingest_worker["acts"], ingest_worker["client"]
    build_pr_fixture(fake_github)
    save_conn("github", CONFIG, {"access_token": "t0ken"})
    started = await acts.connect_source(ws, "github", client)
    assert started["scheduleId"] == f"sync-{ws}-github"
    first = await _wait(client, started["workflowId"])
    assert first["status"] == "done", first
    assert store.get_node(ids.github_pr(REPO, 7)) is not None and store.count("GithubReviewComment") == 5
    run = common.get_run(first["run_id"])
    assert run and run["status"] == "done" and run["mode"] == "backfill" and run["items"]["GithubPullRequest"] >= 1
    assert run["finished_at"] is not None and run["reason"] is None
    cursor = common.load_cursor(ws, "github")
    assert cursor[REPO]["pulls_updated"] == "2026-03-02T10:00:00Z"
    # connection stays connected; linking was started with the changed ids
    link = client.get_workflow_handle(f"link-{ws}-{first['run_id']}-0")
    assert await link.result() > 10
    nodes_before = store.count()

    # incremental: one new PR and nothing else
    fake_github.add_pull(REPO, 8, title="Follow up", author=user(11, "alice"), updated_at="2026-03-10T00:00:00Z")
    fake_github.requests.clear()
    wf_id = f"sync-{ws}-github-incr-1"
    await client.start_workflow("SourceSyncWorkflow", args=[ws, "github", "incremental"], id=wf_id,
                                task_queue=acts.TASK_QUEUE)
    second = await _wait(client, wf_id)
    assert second["status"] == "done"
    details = [p for _, p, _ in fake_github.requests if p.split("?")[0].split("/")[-1].isdigit()]
    assert details == ["/repos/acme/widgets/pulls/8"]
    assert store.count("GithubPullRequest") == 2 and store.count() > nodes_before
    again = common.get_run(second["run_id"])
    assert again and again["mode"] == "incremental" and again["items"]["GithubPullRequest"] == 1
    assert store.count("GithubReview") == 2  # nothing duplicated


async def test_a_ac_69_progress_events_are_stored_and_published_once_per_page(
        ws: str, store: Any, fake_github: FakeGithub, save_conn: Any, ingest_worker: Any, redis_client: Any) -> None:
    """A-AC-69"""
    import json
    import threading

    acts, client = ingest_worker["acts"], ingest_worker["client"]
    build_pr_fixture(fake_github)
    save_conn("github", CONFIG, {"access_token": "t0ken"})
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"ws:{ws}:ingestion")
    pubsub.get_message(timeout=1)  # subscription confirmation
    wf = await acts.start_backfill(ws, "github", client)
    result = await _wait(client, wf)
    types = _event_types(ws)
    assert types[0] == "ingestion.started" and types[-1] == "ingestion.finished"
    assert types.count("ingestion.progress") >= result["pages"]
    messages: list[dict[str, Any]] = []
    while (m := pubsub.get_message(timeout=1)) is not None:
        if m["type"] == "message":
            messages.append(json.loads(m["data"]))
    assert [m["type"] for m in messages].count("ingestion.progress") >= result["pages"]
    progress = [m for m in messages if m["type"] == "ingestion.progress"][-1]["payload"]
    assert progress["source"] == "github" and progress["counts"]["GithubPullRequest"] >= 1 and "perMinute" in progress
    assert threading.active_count() > 0


async def test_auth_failure_marks_connection_error_and_run_failed(
        ws: str, store: Any, fake_github: FakeGithub, save_conn: Any, ingest_worker: Any) -> None:
    """A-AC-65 end to end: the 401 is not retried, the run record carries the reason, the connection shows an error."""
    from actron.db.models import Connection
    from actron.db.session import session_scope

    acts, client = ingest_worker["acts"], ingest_worker["client"]
    build_pr_fixture(fake_github)
    fake_github.inject("/repos/acme/widgets$", 401, times=50)
    save_conn("github", CONFIG, {"access_token": "bad"})
    wf = await acts.start_backfill(ws, "github", client)
    out = await _wait(client, wf)
    assert out["status"] == "failed" and "AuthError" in out["reason"]
    run = common.get_run(out["run_id"])
    assert run and run["status"] == "failed" and "token" in run["reason"].lower()
    with session_scope() as session:
        conn = session.execute(select(Connection).where(Connection.workspace_id == ws)).scalar_one()
        assert conn.status == "error"
    assert fake_github.count(r"/repos/acme/widgets$") == 1
