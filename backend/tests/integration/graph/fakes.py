"""Test doubles for the investigation: a scripted judge and a list-collecting event sink."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from actron.flow.findings import DecisionItem, Question
from actron.flow.investigate import Verdict, template_questions, template_summary


class FakeJudge:
    """J5 stubbed (so seeds come from full text), J6 scripted per decision id, J8 fixed."""

    def __init__(self, restricts: Mapping[str, float] | None = None, *, needs: float = 0.9,
                 rank: Mapping[str, float] | None = None) -> None:
        self.restricts = dict(restricts or {})
        self.needs = needs
        self.rank_scores = dict(rank or {})
        self.conflict_calls: list[str] = []

    async def rank(self, request: str, candidates: Sequence[tuple[str, str]], *, ws: str,
                   request_id: str) -> list[Verdict]:
        if not self.rank_scores:
            return [Verdict(0.0, "stub", True) for _ in candidates]
        return [Verdict(self.rank_scores.get(i, 0.0), "jev", False) for i, _ in candidates]

    async def conflict(self, request: str, decision: DecisionItem, *, ws: str, request_id: str) -> Verdict:
        self.conflict_calls.append(decision.id)
        return Verdict(self.restricts.get(decision.id, 0.05), "jev", False)

    async def needs_question(self, summary: str, conflicts: list[str], max_criticality: float, *, ws: str,
                             request_id: str) -> Verdict:
        return Verdict(self.needs, "jev", False)

    async def questions(self, findings: dict[str, Any], *, ws: str, request_id: str) -> list[Question]:
        return template_questions(findings)

    async def summary(self, findings: dict[str, Any], *, ws: str, request_id: str) -> str:
        return template_summary(findings)


class EventLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, type: str, payload: dict[str, Any], *, actor: str = "actron",
                       surface: str = "system") -> None:
        self.events.append((type, payload))

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [p for t, p in self.events if t == type_]

    def types(self) -> list[str]:
        return [t for t, _ in self.events]
