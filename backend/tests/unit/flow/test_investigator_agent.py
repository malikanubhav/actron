"""The investigator agent with a scripted fake model (spec B, B5). B-AC-23, B-AC-24."""

from __future__ import annotations

import json
from typing import Any

import pytest

from actron.flow import investigator_agent as agent
from actron.flow.investigate import investigate, judge_decisions, label_for
from actron.flow.labels import Thresholds
from actron.graph import queries as Q
from actron.models import AgentTurn, ToolCall
from tests.integration.graph import fixture_graph as fx
from tests.integration.graph.fakes import EventLog, FakeJudge
from tests.integration.graph.fixture_graph import load_fixture_graph

INVENTED = "code:fn:fixture/calva-lite:src/nowhere.ts::madeUp"
SCRIPT: list[list[tuple[str, dict[str, Any]]]] = [
    [("search", {"query": "auto-evaluate on save", "types": ["CodeFunction", "Feature"]})],
    [("decisions_for", {"ids": [fx.EVAL_SAVE]}), ("callers", {"functionId": fx.EVAL_SAVE})],
    [("related_work", {"ids": [fx.EVAL_SAVE]}), ("tests_for", {"ids": [fx.EVAL_SAVE]}),
     ("owners", {"ids": [fx.EVAL_SAVE]}), ("impact", {"ids": [fx.EVAL_SAVE]})],
    [("get_node", {"id": fx.EVAL_SAVE}), ("get_node", {"id": fx.AUTO_EVAL}), ("get_node", {"id": fx.D_SAVE}),
     ("criticality", {"ids": [fx.EVAL_SAVE]}), ("procedures_for", {"ids": [fx.EVAL_SAVE]}),
     ("get_code", {"id": fx.EVAL_SAVE}), ("get_node", {"id": fx.PR101}),
     ("get_node", {"id": fx.LI12}), ("get_node", {"id": fx.M1})],
]
FINAL = {"seedIds": [fx.EVAL_SAVE, fx.AUTO_EVAL, INVENTED], "decisionIds": [fx.D_SAVE, "actron:decision:invented"],
         "relatedWorkIds": [fx.PR101], "notes": "Auto-evaluate on save is constrained by an approved decision."}


class ScriptedModel:
    """Returns the scripted tool calls turn by turn, then the final JSON (and records what it was given)."""

    def __init__(self, script: list[list[tuple[str, dict[str, Any]]]], final: dict[str, Any] | str) -> None:
        self.script = list(script)
        self.final = final
        self.seen_tools: list[int] = []
        self.calls = 0

    async def __call__(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **kw: Any) -> AgentTurn:
        self.calls += 1
        self.seen_tools.append(len(tools))
        if tools and self.script:
            turn = self.script.pop(0)
            return AgentTurn(tool_calls=[ToolCall(id=f"t{self.calls}_{i}", name=n, arguments=a)
                                         for i, (n, a) in enumerate(turn)],
                             tokens={"input": 100, "output": 10}, model="fake/agent")
        content = self.final if isinstance(self.final, str) else "```json\n" + json.dumps(self.final) + "\n```"
        return AgentTurn(content=content, tokens={"input": 50, "output": 20}, model="fake/agent")


@pytest.fixture
def g(indexed_graph: Any) -> Any:
    return load_fixture_graph(indexed_graph)


@pytest.mark.integration
async def test_scripted_agent_events_budget_and_findings(g: Any) -> None:
    """B-AC-23: tool events match the scripted calls, the loop stops at 12 calls, and the findings equal the
    shared query for the agent's seeds."""
    model = ScriptedModel(SCRIPT, FINAL)
    log = EventLog()
    judge = FakeJudge({fx.D_SAVE: 0.92})
    res = await investigate(g.workspace_id, fx.REQUEST_ID, "Turn on auto-evaluate on save by default.", "feature",
                            emit=log, mode="agent", store=g, judge=judge, complete=model, write=False)
    assert res.mode == "agent" and log.of("investigation.started") == [{"mode": "agent"}]
    scripted = [name for turn in SCRIPT for name, _ in turn]
    called = log.of("tool.called")
    assert [c["tool"] for c in called] == scripted[:12]
    assert all(c["by"] == "investigator" for c in called)
    results = log.of("tool.result")
    assert [r["callId"] for r in results] == [c["callId"] for c in called]
    assert all(r["ok"] for r in results)
    assert res.tool_calls == 12
    assert model.seen_tools[-1] == 0  # the last turn is asked to answer without tools
    assert res.tokens.input == 4 * 100 + 50 and res.tokens.output == 4 * 10 + 20

    expected = Q.shared_query(g, fx.REQUEST_ID, [fx.EVAL_SAVE, fx.AUTO_EVAL],
                              {fx.EVAL_SAVE: 1.0, fx.AUTO_EVAL: 0.95}).findings
    await judge_decisions(expected, "Turn on auto-evaluate on save by default.", FakeJudge({fx.D_SAVE: 0.92}),
                          Thresholds(), None, ws="w", request_id="r")
    expected.label = label_for(expected, Thresholds())
    assert res.findings.to_json() == expected.to_json()
    assert res.label == "conflict"


@pytest.mark.integration
async def test_agent_never_keeps_ids_no_tool_returned(g: Any) -> None:
    """B-AC-24: ids in the agent's answer that no tool returned are dropped before findings are built."""
    from actron.mcp_graph.server import graph_client
    from actron.mcp_graph.tools import ToolContext

    ctx = ToolContext(ws=g.workspace_id, store=g, emit=EventLog())
    async with graph_client(ctx) as client:
        out = await agent.run_agent("Turn on auto-evaluate on save by default.", "feature", client=client,
                                    returned_ids=ctx.returned_ids, complete=ScriptedModel(SCRIPT[:2], FINAL))
    assert out.seed_ids == [fx.EVAL_SAVE, fx.AUTO_EVAL] or out.seed_ids == [fx.EVAL_SAVE]
    assert INVENTED not in out.seed_ids and "actron:decision:invented" not in out.decision_ids
    assert set(out.dropped_ids) >= {INVENTED, "actron:decision:invented"}
    assert set(out.seed_ids + out.decision_ids + out.related_ids) <= ctx.returned_ids
    assert out.tool_calls == 3 and not out.stopped_by_budget


class FakeTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def function_schemas(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": "search", "parameters": {}}}]

    async def call(self, name: str, args: Any = None) -> Any:
        self.calls.append(name)
        return [{"id": fx.EVAL_SAVE}]


async def test_budget_counts_individual_calls_and_time() -> None:
    """B-AC-23: at most 12 tool calls run even when one turn asks for more; the time budget also stops it."""
    tools = FakeTools()
    many = [[("search", {"query": str(i)}) for i in range(20)]]
    out = await agent.run_agent("x", "feature", client=tools, returned_ids={fx.EVAL_SAVE},
                                complete=ScriptedModel(many, FINAL))
    assert len(tools.calls) == 12 and out.tool_calls == 12 and out.stopped_by_budget
    assert out.seed_ids == [fx.EVAL_SAVE]

    ticks = iter([0.0, 0.0, 500.0, 500.0, 500.0, 500.0])
    tools2 = FakeTools()
    out2 = await agent.run_agent("x", "feature", client=tools2, returned_ids=set(),
                                 complete=ScriptedModel([[("search", {})]] * 5, FINAL), clock=lambda: next(ticks))
    assert out2.stopped_by_budget and len(tools2.calls) <= 1


async def test_unparseable_final_answer_fails() -> None:
    """B-AC-23: an answer that is not JSON is a failure (the caller retries, then falls back)."""
    with pytest.raises(agent.AgentFailed):
        await agent.run_agent("x", "feature", client=FakeTools(), returned_ids=set(),
                              complete=ScriptedModel([], "I could not find anything."))
    assert agent.parse_final('Here: {"seedIds": []} done') == {"seedIds": []}
