"""Context pack (`code.md`) and TASK.md (spec B, B9 step 2; B-AC-69, B-AC-66)."""

from __future__ import annotations

from typing import Any

from actron.flow.build import WORK_PROTOCOL, render_task_md
from actron.flow.context_pack import PACK_LIMIT, build_context_pack, empty_tools
from tests.integration.build.conftest import ADD_ID, EVIDENCE, TICKET, TOTAL_ID, FakeGraphTools


async def test_pack_contains_every_part() -> None:
    """B-AC-69: full source, callers and callees with call-site snippets, covering tests, outlines, constraints,
    procedure."""
    tools = FakeGraphTools()
    pack = await build_context_pack(TICKET, EVIDENCE, [], tools=tools, test_command="pytest -q", snapshot="abc123")
    md = pack.markdown
    assert pack.tier == "full" and pack.size <= PACK_LIMIT
    assert "Snapshot: `abc123`" in md
    assert "## `add` — `calc/ops.py:1-2`" in md
    assert "1 | def add(a, b):" in md and "2 |     return a + b" in md
    assert "### Callers" in md and "`total` (calc/ops.py:8)" in md
    assert "result = add(result, item)" in md  # call-site snippet with context
    assert "### Callees" in md
    assert "#### `test_add` (tests/test_ops.py)" in md and "assert add(2, 3) == 5" in md
    assert "add keeps its signature" in md and "Let's never change add's arguments" in md
    assert "# File outlines" in md and "`def total(items)` (lines 5-9)" in md
    assert "# How changes are tested here" in md and "`calc/ops.py`, `tests/test_ops.py`" in md
    called = {name for name, _ in tools.calls}
    assert {"get_code", "callers", "references", "callees", "tests_for", "decisions_for", "file_outline",
            "procedures_for"} <= called
    assert pack.meta[ADD_ID] == {"path": "calc/ops.py", "hasCallers": True, "callersInPack": True}
    assert pack.where_to_work() == ["- `add` in `calc/ops.py` (lines 1-2)"]


class BigTools(FakeGraphTools):
    """Large bodies so the pack must shrink."""

    async def __call__(self, name: str, args: dict[str, Any]) -> Any:
        value = await super().__call__(name, args)
        if name == "get_code" and isinstance(value, dict):
            value = dict(value, code="\n".join(f"    x{i} = {i}  # filler line" for i in range(n_lines(value))))
        if name == "references":
            value = [dict(r, snippet="\n".join(["    pass  # snippet"] * 400)) for r in value]
        return value


def n_lines(value: dict[str, Any]) -> int:
    return 1500 if value["id"] == ADD_ID else 100


async def test_pack_respects_limit_with_documented_fallback() -> None:
    """B-AC-69: over 60,000 characters → full source for affected symbols, outlines and names for the rest,
    and which tool to call for more."""
    pack = await build_context_pack(TICKET, EVIDENCE, [], tools=BigTools(), test_command="pytest -q")
    assert pack.size <= PACK_LIMIT
    assert pack.tier == "compact"
    md = pack.markdown
    assert "x1499 = 1499" in md  # affected symbol still complete
    assert "Call references with id" in md and "shortened to fit 60,000 characters" in md
    assert "result = add(result, item)" not in md  # call sites left out
    assert "`total` (calc/ops.py:8)" in md  # callers still named


async def test_pack_cut_tier_names_get_code_range() -> None:
    """B-AC-69: when even the affected source does not fit, it is cut and get_code_range is named."""
    pack = await build_context_pack(TICKET, EVIDENCE, [], tools=BigTools(), limit=20_000)
    assert pack.size <= 20_000 and pack.tier == "cut"
    assert "Call get_code_range with path `calc/ops.py`" in pack.markdown
    assert pack.meta[ADD_ID]["callersInPack"] is False


async def test_pack_without_graph_says_so() -> None:
    pack = await build_context_pack(TICKET, EVIDENCE, [], tools=empty_tools)
    assert "Source not available from the graph. Call get_code" in pack.markdown
    assert pack.meta[ADD_ID]["hasCallers"] is False


async def test_differing_files_are_included_from_checkout(tmp_path: Any) -> None:
    """B-AC-80: files that differ on a non-working target branch are included from the checkout and marked."""
    (tmp_path / "calc").mkdir()
    (tmp_path / "calc" / "ops.py").write_text("def add(a, b):\n    return b + a\n")
    pack = await build_context_pack(TICKET, EVIDENCE, [], tools=FakeGraphTools(), differing_files=["calc/ops.py"],
                                    target_branch="release-1", repo_dir=tmp_path)
    assert "## `calc/ops.py` (differs on release-1)" in pack.markdown
    assert "return b + a" in pack.markdown


def test_task_md_exact_structure() -> None:
    """B-AC-66 and B9: TASK.md has the exact sections, the procedure's test command and co-changed paths."""
    procs = [{"testCommand": "pytest -q", "coChangedPaths": ["calc/ops.py", "CHANGELOG.md"]}]
    text = render_task_md(TICKET, EVIDENCE, procs, where_to_work=["- `add` in `calc/ops.py` (lines 1-2)"],
                          test_command="pytest -q")
    lines = text.splitlines()
    assert lines[0] == "# Task" and lines[1] == "Add a subtract function to calc.ops."
    order = ["## Acceptance criteria", "## Constraints you must preserve (each with its evidence)",
             "## Where to work", "## How changes are validated here",
             "## Work protocol (follow every step, in order)", "## Rules (non-negotiable)"]
    idx = [lines.index(h) for h in order]
    assert idx == sorted(idx)
    assert ("- add keeps its signature — evidence: Let's never change add's arguments, plugins call it. "
            "(https://example.slack.com/archives/C1/p10)") in lines
    assert "Test command: `pytest -q`" in lines
    assert "Files that usually change together: `CHANGELOG.md`, `calc/ops.py`" in lines
    assert text.endswith(WORK_PROTOCOL)
    assert "1. Read /context/code.md completely." in text and "10. Finish by writing /context/REPORT.json" in text
    with_reminder = render_task_md(TICKET, EVIDENCE, procs, where_to_work=[], test_command="pytest -q",
                                   reminders=["Use the graph tools."])
    assert with_reminder.startswith("## Reminder from the last attempt (read this first)\n- Use the graph tools.")


def test_total_id_is_a_caller_id() -> None:
    assert TOTAL_ID.endswith("::total")
