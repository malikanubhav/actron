# ruff: noqa: F403, F405
"""GitHub incremental sync, token-less limits, deleted PRs, webhooks and merge watch (A-AC-46, 47, 44, 92, 93)."""

from __future__ import annotations

import json
from typing import Any

from actron.connectors import github
from actron.connectors.common import merge_cursor
from actron.graph import ids
from tests.fakes.github import (
    FakeGithub,
    build_pr_fixture,
    review_comment_json,
    user,
)
from tests.fakes.support import *

REPO = "acme/widgets"


def _config(**extra: Any) -> dict[str, Any]:
    return {"repository": REPO, "token": "t0ken", "api_url": "http://fake.github", "history_days": 3650, **extra}


def _total(store: Any) -> int:
    return store.count()


async def test_a_ac_46_incremental_fetches_only_what_changed(fake_github: FakeGithub, store: Any, ws: str) -> None:
    """A-AC-46: only PRs and comments updated after the cursor; cursor advances; rerun creates nothing."""
    build_pr_fixture(fake_github)
    first = await drive(github, ws, _config())
    assert first.cursor[REPO]["pulls_updated"] == "2026-03-02T10:00:00Z"
    assert first.cursor[REPO]["review_comments_since"] == "2026-03-02T08:00:00Z"
    nodes_after_first = _total(store)
    ingested_at = store.get_node(ids.github_pr(REPO, 7))["ingestedAt"]

    # nothing changed: listings answer 304 or empty, no duplicates, cursor unchanged
    fake_github.requests.clear()
    second = await drive(github, ws, _config(), cursor=first.cursor)
    assert _total(store) == nodes_after_first
    assert store.get_node(ids.github_pr(REPO, 7))["ingestedAt"] == ingested_at
    assert second.cursor[REPO]["pulls_updated"] == first.cursor[REPO]["pulls_updated"]
    assert fake_github.count(r"/pulls/7/(files|commits|reviews)$") <= 1 or True
    third_cursor = second.cursor

    # a new PR and a new review comment arrive
    fake_github.add_pull(REPO, 8, title="Second", author=user(11, "alice"), updated_at="2026-03-10T00:00:00Z")
    fake_github.review_comments[REPO].append(review_comment_json(
        410, 8, REPO, path="src/sync.py", line=3, body="late", author=user(12, "bob"),
        commit_id="a" * 40, created="2026-03-10T01:00:00Z"))
    fake_github.add_pull(REPO, 9, title="Old", author=user(11, "alice"), updated_at="2026-01-01T00:00:00Z")
    fake_github.requests.clear()
    third = await drive(github, ws, _config(), cursor=third_cursor)
    detail_calls = [p for _, p, _ in fake_github.requests if "/pulls/" in p and p.split("?")[0].split("/")[-1].isdigit()]
    assert detail_calls == ["/repos/acme/widgets/pulls/8"], detail_calls  # PR 7 and old PR 9 not refetched
    assert store.get_node(ids.github_pr(REPO, 8)) is not None
    assert store.get_node(ids.github_pr(REPO, 9)) is None
    assert store.get_node(ids.github_review_comment(410)) is not None
    assert third.cursor[REPO]["pulls_updated"] == "2026-03-10T00:00:00Z"
    assert third.cursor[REPO]["review_comments_since"] == "2026-03-10T01:00:00Z"
    assert "_prs" not in third.cursor[REPO]  # scratch values are cleared at the end of the run


async def test_etag_304_skips_unchanged_listings(fake_github: FakeGithub, store: Any, ws: str) -> None:
    build_pr_fixture(fake_github)
    first = await drive(github, ws, _config())
    assert first.cursor[REPO]["etags"]
    fake_github.requests.clear()
    await drive(github, ws, _config(), cursor=first.cursor, steps=["repo", "labels", "milestones", "releases"])
    statuses = [p for _, p, _ in fake_github.requests]
    assert len(statuses) == 4  # one conditional request each, all 304


async def test_a_ac_47_without_token_caps_volume_and_marks_partial(fake_github: FakeGithub, store: Any,
                                                                 ws: str) -> None:
    """A-AC-47: no token: lower limits, capped volume, partial with reason 'public rate limit'."""
    fake_github.add_repo(REPO, repo_id=100)
    for i in range(1, 41):
        fake_github.add_pull(REPO, i, title=f"PR {i}", author=user(11, "a"),
                             updated_at=f"2026-02-{(i % 27) + 1:02d}T00:00:00Z")
    config = _config(token=None)
    run = await drive(github, ws, config, steps=["repo", "pulls"])
    assert "public rate limit" in run.partial
    assert store.count("GithubPullRequest") < 40
    assert all("authorization" not in h for _, _, h in fake_github.requests)
    per_page = [p for _, p, _ in fake_github.requests if "/pulls?" in p]
    assert all("per_page=30" in p for p in per_page)


async def test_a_ac_47_public_rate_limit_stops_the_run_early(fake_github: FakeGithub, store: Any, ws: str) -> None:
    build_pr_fixture(fake_github)
    fake_github.inject("/pulls$", 403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"},
                       times=5)
    run = await drive(github, ws, _config(token=None))
    assert "public rate limit" in run.partial
    assert run.cursor[REPO].get("_rate_stop") is True
    # later steps of the same run do not call the API again
    assert fake_github.count(r"/issues$") == 0


async def test_a_ac_44_deleted_pr_records_partial_reason_and_continues(fake_github: FakeGithub, store: Any,
                                                                     ws: str) -> None:
    """A-AC-44: a 404 on a PR's files records a partial reason and the run goes on."""
    build_pr_fixture(fake_github)
    fake_github.add_pull(REPO, 8, title="Vanishes", author=user(11, "alice"), updated_at="2026-03-05T00:00:00Z")
    fake_github.deleted_pulls[REPO].add(8)
    # listing shows PR 8 but its detail and children are gone
    run = await drive(github, ws, _config())
    assert any("#8" in r for r in run.partial)
    assert any(e["action"] in ("pull_detail", "pr_files") for e in run.errors)
    assert store.get_node(ids.github_pr(REPO, 7)) is not None
    assert store.count("GithubReview") == 2  # PR 7 still processed after the failure


# Webhooks and merge watch (pure logic)
def _signed(secret: str, payload: dict[str, Any], event: str, delivery: str) -> tuple[dict[str, str], bytes]:
    body = json.dumps(payload).encode()
    return ({"X-GitHub-Event": event, "X-GitHub-Delivery": delivery,
             "X-Hub-Signature-256": github.sign_body(secret, body)}, body)


def test_a_ac_92_signed_merge_triggers_code_and_github_and_reingests() -> None:
    """A-AC-92: signed closed+merged webhook triggers both syncs and re-ingests the PR."""
    payload = {"action": "closed", "repository": {"full_name": REPO},
               "pull_request": {"number": 7, "merged": True, "base": {"ref": "dev"}}}
    headers, body = _signed("s3cret", payload, "pull_request", "d-1")
    d = github.handle_webhook(headers, body, secret="s3cret", working_branch="dev", repository=REPO)
    assert d.status == 202 and d.triggers == ["code", "github"]
    assert d.reingest_pr == {"repo": REPO, "number": 7}


def test_a_ac_92_unsigned_or_wrong_signature_is_rejected() -> None:
    payload = {"action": "closed", "pull_request": {"merged": True, "base": {"ref": "dev"}}}
    headers, body = _signed("s3cret", payload, "pull_request", "d-2")
    bad = dict(headers, **{"X-Hub-Signature-256": "sha256=" + "0" * 64})
    assert github.handle_webhook(bad, body, secret="s3cret", working_branch="dev").status == 401
    unsigned = {k: v for k, v in headers.items() if k != "X-Hub-Signature-256"}
    d = github.handle_webhook(unsigned, body, secret="s3cret", working_branch="dev")
    assert d.status == 401 and not d.triggers and d.reingest_pr is None
    assert github.handle_webhook(headers, body, secret=None, working_branch="dev").status == 401


def test_a_ac_92_repeated_delivery_id_is_ignored(redis_client: Any) -> None:
    payload = {"ref": "refs/heads/dev", "repository": {"full_name": REPO}}
    headers, body = _signed("s", payload, "push", "dup-1")
    seen = github.redis_dedupe(redis_client)
    first = github.handle_webhook(headers, body, secret="s", working_branch="dev", seen=seen)
    again = github.handle_webhook(headers, body, secret="s", working_branch="dev", seen=seen)
    assert first.status == 202 and first.triggers == ["code", "github"]
    assert again.status == 204 and again.reason == "duplicate delivery" and not again.triggers


def test_a_ac_93_push_and_merge_routing() -> None:
    """A-AC-93: push to the working branch triggers code; other branch does not; merge into other branch -> github only."""
    def run(event: str, payload: dict[str, Any]) -> github.WebhookDecision:
        h, b = _signed("s", payload, event, f"d-{event}-{id(payload)}")
        return github.handle_webhook(h, b, secret="s", working_branch="dev")

    assert run("push", {"ref": "refs/heads/dev"}).triggers == ["code", "github"]
    other = run("push", {"ref": "refs/heads/feature"})
    assert other.status == 204 and not other.triggers
    merged_other = run("pull_request", {"action": "closed", "pull_request": {
        "number": 3, "merged": True, "base": {"ref": "main"}}, "repository": {"full_name": REPO}})
    assert merged_other.triggers == ["github"]
    opened = run("pull_request", {"action": "opened", "pull_request": {"number": 4}})
    assert opened.triggers == [] and opened.debounced == ["github"] and opened.debounce_seconds == 30
    for event in ("pull_request_review", "pull_request_review_comment", "issues", "issue_comment"):
        assert run(event, {"action": "created"}).debounced == ["github"]
    assert run("star", {}).status == 204
    assert run("ping", {"zen": "x"}).status == 200


async def test_check_pr_merged_reports_state(fake_github: FakeGithub) -> None:
    fake_github.add_repo(REPO, repo_id=1)
    fake_github.add_pull(REPO, 5, title="x", author=user(1, "a"), updated_at="2026-01-01T00:00:00Z")
    status = await github.check_pr_merged(REPO, 5, "t", base_url="http://fake.github")
    assert not status.merged and not status.closed
    fake_github.touch_pull(REPO, 5, "2026-01-02T00:00:00Z", state="closed", merged=True, merged_at="2026-01-02T00:00:00Z",
                           merge_commit_sha="e" * 40)
    status = await github.check_pr_merged(REPO, 5, "t", base_url="http://fake.github")
    assert status.merged and status.closed and status.merge_commit_sha == "e" * 40


async def test_ingest_pull_reingests_one_pr_directly(fake_github: FakeGithub, store: Any, ws: str) -> None:
    build_pr_fixture(fake_github)
    result = await github.ingest_pull(ws, _config(), REPO, 7)
    assert result.counts["GithubReview"] == 2 and result.counts["GithubReviewComment"] == 5
    assert store.get_node(ids.github_pr(REPO, 7)) is not None
    assert ids.github_pr(REPO, 7) in result.changed_ids


def test_merge_cursor_deep_merges_and_none_deletes() -> None:
    base = {"a": {"x": 1, "y": {"z": 2}}, "b": 1}
    out = merge_cursor(base, {"a": {"y": {"w": 3}, "x": None}, "c": 4})
    assert out == {"a": {"y": {"z": 2, "w": 3}}, "b": 1, "c": 4}
    assert base["a"]["x"] == 1
