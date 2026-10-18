"""Workspaces from Slack sign-in (spec B, B12a): owner, member, separate teams (B-AC-83)."""

from __future__ import annotations

import uuid

from actron.api.auth import sign_in_slack_user
from actron.db import models as m
from actron.db.session import session_scope
from tests.api._fixtures import W6Env


def _claims(team: str, user: str, team_name: str = "Acme Eng") -> dict[str, str]:
    return {"https://slack.com/team_id": team, "https://slack.com/team_name": team_name,
            "https://slack.com/user_id": user, "name": user}


def _role(user_id: str, ws: str) -> str | None:
    with session_scope() as s:
        mem = s.get(m.Membership, (uuid.UUID(user_id), ws))
        return mem.role if mem else None


def test_first_user_owner_second_member_other_team_separate(w6: W6Env) -> None:
    """B-AC-83: first sign-in creates the workspace as owner; same team joins as member; other team separate."""
    team = f"T{uuid.uuid4().hex[:8]}"
    name = f"Acme {uuid.uuid4().hex[:4]}"
    u1, ws1 = sign_in_slack_user(_claims(team, f"U1{team}", name))
    u2, ws2 = sign_in_slack_user(_claims(team, f"U2{team}", name))
    assert ws1 == ws2
    assert _role(u1, ws1) == "owner" and _role(u2, ws1) == "member"
    other = f"T{uuid.uuid4().hex[:8]}"
    u3, ws3 = sign_in_slack_user(_claims(other, f"U3{other}", name))
    assert ws3 != ws1 and _role(u3, ws3) == "owner"
    with session_scope() as s:
        row = s.get(m.Workspace, ws1)
        assert row is not None and row.slack_team_id == team and row.graph_name == f"actron_{ws1.replace('-', '_')}"


def test_signing_in_again_keeps_role(w6: W6Env) -> None:
    team = f"T{uuid.uuid4().hex[:8]}"
    u1, ws = sign_in_slack_user(_claims(team, f"U{team}"))
    again, ws_again = sign_in_slack_user(_claims(team, f"U{team}"))
    assert (again, ws_again) == (u1, ws) and _role(u1, ws) == "owner"
