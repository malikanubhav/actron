"""Live Linear checks (opt-in): every query the product sends is valid against Linear's real schema (A10 [VERIFY]).

Run: `./scripts/live_smoke.sh linear` with LINEAR_API_KEY (and LINEAR_TEAM_ID) in .env. Read-only: nothing is
created here; the ticket-sync issue is created by the product flow, not by this test.
"""

from __future__ import annotations

import os

import pytest

from actron.integrations import linear_client as lc
from actron.integrations.linear_client import LinearClient

pytestmark = [pytest.mark.live, pytest.mark.timeout(120)]


@pytest.fixture
def key() -> str:
    value = os.environ.get("LINEAR_API_KEY", "")
    if not value:
        pytest.skip("LINEAR_API_KEY is not set")
    return value


async def test_viewer_and_teams_and_team_access(key: str) -> None:
    async with LinearClient(key) as client:
        viewer = await client.viewer()
        assert viewer["id"] and viewer["organization"]["id"]
        teams, _ = await client.connection(lc.Q_TEAMS, "teams", {})
        assert teams and {"id", "name", "key"} <= set(teams[0])
        team_id = os.environ.get("LINEAR_TEAM_ID") or teams[0]["id"]
        access = await client.query(lc.Q_TEAM_ACCESS, {"id": team_id})
        assert access["team"]["id"] == team_id and access["viewer"]["guest"] is False


async def test_every_ingestion_query_is_valid(key: str) -> None:
    """Each read query runs without a schema error and returns the fields the connector maps."""
    async with LinearClient(key) as client:
        teams, _ = await client.connection(lc.Q_TEAMS, "teams", {})
        team = os.environ.get("LINEAR_TEAM_ID") or teams[0]["id"]
        users, _ = await client.connection(lc.Q_USERS, "users", {})
        assert users and {"id", "name", "displayName", "active"} <= set(users[0])
        states, _ = await client.connection(lc.Q_STATES, "workflowStates", {"team": team})
        assert states and {"id", "name", "type", "position"} <= set(states[0])
        await client.connection(lc.Q_LABELS, "issueLabels", {"team": team})
        await client.connection(lc.Q_PROJECTS, "projects", {})
        issues, _ = await client.connection(
            lc.Q_ISSUES, "issues", {"team": team, "since": "2000-01-01T00:00:00.000Z"}
        )
        await client.connection(lc.Q_ISSUES_ALL_TEAMS, "issues", {"since": "2000-01-01T00:00:00.000Z"})
        if issues:
            found = await client.issue(issues[0]["id"])
            assert found and found["id"] == issues[0]["id"]
            await client.query(lc.Q_COMMENTS, {"id": issues[0]["id"], "after": None})
