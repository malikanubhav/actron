"""Graph fixtures for W5's query tests: `small_graph` is `indexed_graph` with the fixture graph loaded."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.graph.fixture_graph import load_fixture_graph


@pytest.fixture
def small_graph(indexed_graph: Any) -> Any:
    return load_fixture_graph(indexed_graph)
