# ruff: noqa: F403, F405
"""Linear mapping, incremental pulls, edit history and external edits: A-AC-57, 58, 61, 62, 104 (graph needed)."""

from __future__ import annotations

from typing import Any

from actron.connectors import linear
from actron.graph import ids
from tests.fakes.linear import FakeLinear, build_team_fixture
from tests.fakes.support import *


def _config(**extra: Any) -> dict[str, Any]:
    return {"token": "lin_api_test", "api_url": "http://fake.linear/graphql", "team": "t1", "history_days": 3650,
            **extra}


def _rows(store: Any, cypher: str, **params: Any) -> list[dict[str, Any]]:
    return store.query(cypher, params, read_only=True)


def _edge(store: Any, rel: str, a: str, b: str) -> int:
    return int(_rows(store, f"MATCH (a:{a})-[r:{rel}]->(b:{b}) RETURN count(r) AS c")[0]["c"])


async def test_a_ac_57_teams_users_states_labels_projects_issues_comments_map(fake_linear: FakeLinear, store: Any,
                                                                            ws: str) -> None:
    """A-AC-57: documented nodes and links, including issues with paginated comments."""
    build_team_fixture(fake_linear)
    run = await drive(linear, ws, _config())
    n = store.count
    assert n("LinearTeam") == 1 and n("LinearUser") == 2 and n("LinearState") == 3
    assert n("LinearLabel") == 2 and n("LinearProject") == 1 and n("LinearIssue") == 2
    assert n("LinearComment") == 60  # 50 on the first page plus 10 fetched separately
    issue = store.get_node(ids.linear_issue("i1"))
    assert issue["identifier"] == "ENG-1" and issue["title"] == "Retry on rate limit"
    assert issue["stateId"] == "s2" and issue["stateType"] == "started" and issue["assigneeId"] == "u1"
    assert issue["teamId"] == "t1" and issue["projectId"] == "p1" and issue["labelIds"] == ["l1"]
    assert issue["creatorId"] == "u2" and issue["priority"] == 2 and issue["number"] == 1 and issue["version"] == 1
    assert issue["url"].endswith("ENG-1") and issue["branchName"] == "ada/eng-1-retry"
    assert store.get_node(ids.linear_team("t1"))["key"] == "ENG"
    assert store.get_node(ids.linear_user("u1"))["email"] == "ada@acme.test"
    assert store.get_node(ids.linear_state("s3"))["type"] == "completed"
    expected = {
        ("DEFINES_WORKFLOW", "LinearTeam", "LinearState"): 3, ("USES_LABEL", "LinearTeam", "LinearLabel"): 2,
        ("BELONGS_TO_TEAM", "LinearIssue", "LinearTeam"): 2, ("HAS_STATE", "LinearIssue", "LinearState"): 2,
        ("ASSIGNED_TO", "LinearIssue", "LinearUser"): 1, ("ISSUE_CREATED_BY", "LinearIssue", "LinearUser"): 2,
        ("BELONGS_TO_PROJECT", "LinearIssue", "LinearProject"): 1, ("CONTAINS_ISSUE", "LinearProject", "LinearIssue"): 1,
        ("SUBISSUE_OF", "LinearIssue", "LinearIssue"): 1, ("HAS_LABEL", "LinearIssue", "LinearLabel"): 1,
        ("HAS_COMMENT", "LinearIssue", "LinearComment"): 60, ("CREATED_BY", "LinearComment", "LinearUser"): 60,
        ("REPLIES_TO", "LinearComment", "LinearComment"): 1, ("MENTIONS_USER", "LinearComment", "LinearUser"): 1,
    }
    for (rel, a, b), want in expected.items():
        assert _edge(store, rel, a, b) == want, (rel, _edge(store, rel, a, b), want)
    mention = _rows(store, "MATCH (c:LinearComment)-[:MENTIONS_USER]->(u:LinearUser) RETURN c.id AS c, u.id AS u")
    assert mention == [{"c": ids.linear_comment("c2"), "u": ids.linear_user("u2")}]
    assert not run.partial and run.cursor["issues_updated"] == "2026-03-05T00:00:00.000Z"
    assert len(fake_linear.calls("IssueComments")) == 1


async def test_a_ac_58_incremental_pull_filters_by_updated_at_and_advances_cursor(fake_linear: FakeLinear,
                                                                                store: Any, ws: str) -> None:
    """A-AC-58"""
    build_team_fixture(fake_linear)
    first = await drive(linear, ws, _config())
    fake_linear.requests.clear()
    quiet = await drive(linear, ws, _config(), cursor=first.cursor)
    assert quiet.counts.get("LinearIssue", 0) == 0 and not quiet.changed
    assert fake_linear.calls("Issues")[0]["since"] == "2026-03-05T00:00:00.000Z"
    fake_linear.add_issue("i3", "t1", 3, "ENG", "New work", updated_at="2026-03-20T00:00:00.000Z", state="s1")
    fake_linear.edit_issue("i2", updated_at="2026-03-21T00:00:00.000Z", priority=1)  # not a text change
    second = await drive(linear, ws, _config(), cursor=quiet.cursor)
    assert second.cursor["issues_updated"] == "2026-03-21T00:00:00.000Z"
    assert ids.linear_issue("i3") in second.changed and ids.linear_issue("i2") not in second.changed
    assert store.get_node(ids.linear_issue("i2"))["priority"] == 1
    assert store.count("LinearIssue") == 3


async def test_a_ac_104_edited_description_and_comment_create_previous_versions(fake_linear: FakeLinear,
                                                                               store: Any, ws: str) -> None:
    """A-AC-104 (ingestion side): previous-version nodes and links; changed ids include the edited ones."""
    build_team_fixture(fake_linear)
    first = await drive(linear, ws, _config())
    fake_linear.edit_issue("i1", updated_at="2026-03-30T00:00:00.000Z", description="Sync crashes on 429 and 403.")
    fake_linear.comments["i1"][4]["body"] = "comment 5 (edited)"
    fake_linear.comments["i1"][4]["editedAt"] = "2026-03-30T00:00:00.000Z"
    second = await drive(linear, ws, _config(), cursor=first.cursor)
    iid, cid = ids.linear_issue("i1"), ids.linear_comment("c5")
    assert iid in second.changed and cid in second.changed
    issue = store.get_node(iid)
    assert issue["description"] == "Sync crashes on 429 and 403." and issue["version"] == 2
    assert store.get_node(iid + "@v1")["description"] == "Sync crashes on 429."
    assert _edge(store, "ISSUE_PREVIOUS_VERSION", "LinearIssue", "LinearIssue") == 1
    comment = store.get_node(cid)
    assert comment["body"] == "comment 5 (edited)" and comment["version"] == 2
    assert store.get_node(cid + "@v1")["body"] == "comment 5"
    assert _edge(store, "COMMENT_PREVIOUS_VERSION", "LinearComment", "LinearComment") == 1
    # a second edit creates @v2; an unchanged pull creates nothing
    fake_linear.edit_issue("i1", updated_at="2026-04-02T00:00:00.000Z", title="Retry on rate limit (v2)")
    third = await drive(linear, ws, _config(), cursor=second.cursor)
    assert store.get_node(iid)["version"] == 3 and store.get_node(iid + "@v2")["title"] == "Retry on rate limit"
    assert iid in third.changed
    total = store.count()
    await drive(linear, ws, _config(), cursor=third.cursor)
    assert store.count() == total


async def test_a_ac_62_branch_name_is_stored_and_attachments_become_urls(fake_linear: FakeLinear, store: Any,
                                                                        ws: str) -> None:
    """A-AC-62 and A-AC-104: branchName and attachment URLs are stored for linking."""
    build_team_fixture(fake_linear)
    await drive(linear, ws, _config())
    issue = store.get_node(ids.linear_issue("i1"))
    assert issue["branchName"] == "ada/eng-1-retry"
    assert issue["attachmentUrls"] == ["https://github.com/acme/widgets/pull/7"]


async def test_without_a_team_every_team_is_read(fake_linear: FakeLinear, store: Any, ws: str) -> None:
    build_team_fixture(fake_linear)
    fake_linear.add_team("t2", "OPS", "Operations")
    fake_linear.add_state("t2", "s9", "Open", "unstarted")
    fake_linear.add_issue("i9", "t2", 1, "OPS", "Ops work", updated_at="2026-03-02T00:00:00.000Z", state="s9")
    scoped = await drive(linear, ws, _config())
    assert store.get_node(ids.linear_issue("i9")) is None and scoped.cursor["_teams"] == ["t1"]
    await drive(linear, ws, _config(team=None))
    assert store.get_node(ids.linear_issue("i9")) is not None
    assert store.count("LinearTeam") == 2


async def test_rate_limit_mid_run_is_retryable(fake_linear: FakeLinear, store: Any, ws: str) -> None:
    import pytest

    from actron.connectors.common import RetryableProviderError

    build_team_fixture(fake_linear)
    fake_linear.rate_limit("Issues")
    with pytest.raises(RetryableProviderError) as err:
        await drive(linear, ws, _config())
    assert err.value.retry_after == 7
