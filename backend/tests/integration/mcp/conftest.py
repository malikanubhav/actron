"""MCP fixtures: the fixture graph, a tool context with a list-collecting event sink."""

from __future__ import annotations

from typing import Any

import pytest

from actron.mcp_graph.tools import ToolContext
from tests.integration.graph.fixture_graph import load_fixture_graph


class EventLog:
    """A list-collecting EventSink (W6's real sink writes to PostgreSQL and Redis)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, type: str, payload: dict[str, Any], *, actor: str = "actron",
                       surface: str = "system") -> None:
        self.events.append((type, payload))

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [p for t, p in self.events if t == type_]


@pytest.fixture
def small_graph(indexed_graph: Any) -> Any:
    return load_fixture_graph(indexed_graph)


@pytest.fixture
def events() -> EventLog:
    return EventLog()


@pytest.fixture
def tool_ctx(small_graph: Any, events: EventLog) -> ToolContext:
    return ToolContext(ws=small_graph.workspace_id, store=small_graph, emit=events, by="investigator")
