"""Seeds from names written in the request (B5 fallback pipeline, added after the first live run on Calva)."""

from __future__ import annotations

from typing import Any

from actron.graph import queries as Q


def test_explicit_identifiers_finds_code_shaped_names() -> None:
    """B-AC-25: camelCase, snake_case, PascalCase and backticked names are picked; plain words are not."""
    text = "Make `repl.evaluateCode` and docFromTextNotation handle read_log output in NReplSession please"
    assert Q.explicit_identifiers(text) == ["evaluateCode", "docFromTextNotation", "read_log", "NReplSession"]
    assert Q.explicit_identifiers("Make the output window wrap long lines") == []


def test_seeds_by_name_returns_exact_matches_first(small_graph: Any) -> None:
    """B-AC-25: a function named in the request becomes a seed with score 1.0, even if full-text ranks it low."""
    rows = Q.seeds_by_name(small_graph, "Change formatEvalResult so maps print on one line")
    assert [r.id for r in rows] == ["code:fn:fixture/calva-lite:src/evaluate.ts::formatEvalResult"]
    assert rows[0].explicit and rows[0].score == 1.0


def test_criticality_question_quotes_real_caller_counts(small_graph: Any) -> None:
    """B-AC-30: the question names the function's own callers from the graph, split into code and tests."""
    from actron.flow.investigate import _callers_phrase

    phrase = _callers_phrase(small_graph, "code:fn:fixture/calva-lite:src/evaluate.ts::evaluateCode", 99)
    assert phrase.startswith("is called from ")
    assert "99" not in phrase
    assert _callers_phrase(None, "x", 3) == "is used by 3 other functions"


def test_seeds_by_name_ignores_unknown_names(small_graph: Any) -> None:
    """B-AC-25: an identifier that is not in the graph yields no seed (nothing is invented)."""
    assert Q.seeds_by_name(small_graph, "Fix notARealFunction please") == []
