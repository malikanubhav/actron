"""Writing jobs with a fake LLM, and the investigator's tool-calling turn (spec A, A13; spec B, B5)."""

from __future__ import annotations

from collections.abc import Callable

from actron import models
from tests.fakes.llm import FakeLLM, json_reply

FINDINGS = {
    "seeds": [{"id": "code:fn:a/b:src/x.ts::f", "type": "CodeFunction", "score": 0.9}],
    "decisions": [
        {
            "id": "actron:decision:1",
            "statement": "Keep strict mode.",
            "status": "approved",
            "conflict": {"label": "conflict", "probability": 0.9},
        }
    ],
}


async def test_write_questions_filters_unknown_evidence(llm_on: Callable[..., FakeLLM]) -> None:
    """B6 via A13: at most 3 questions; evidence ids limited to ids in the findings."""
    qs = [
        {
            "questionId": f"q{i}",
            "text": "Should strict mode stay?",
            "kind": "choice",
            "options": [{"value": "y", "label": "Yes"}],
            "evidenceIds": ["actron:decision:1", "made:up"],
        }
        for i in range(5)
    ]
    llm_on([json_reply(questions=qs)])
    out = await models.write_questions(FINDINGS)
    assert len(out) == 3 and out[0].evidenceIds == ["actron:decision:1"]


async def test_write_ticket_validates_schema(llm_on: Callable[..., FakeLLM]) -> None:
    """B.C5 via A13: the LLM ticket is validated; ids outside the findings are dropped."""
    ticket = {
        "objective": "Add a setting.",
        "context": "c",
        "acceptanceCriteria": ["Given a when b then c"],
        "constraintsToPreserve": [
            {"text": "Keep strict mode.", "evidenceIds": ["actron:decision:1"]}
        ],
        "affectedFunctions": ["code:fn:a/b:src/x.ts::f", "code:fn:invented"],
        "testPlan": [{"kind": "new", "target": "t", "command": "npm test"}],
        "outOfScope": [],
        "targetBranch": "dev",
    }
    llm_on([json_reply(**ticket)])
    t = await models.write_ticket("Add a setting", FINDINGS, [])
    assert (
        not t.stub
        and t.affectedFunctions == ["code:fn:a/b:src/x.ts::f"]
        and t.targetBranch == "dev"
    )


async def test_invalid_ticket_falls_back_to_template(llm_on: Callable[..., FakeLLM]) -> None:
    """A13: an invalid ticket twice -> deterministic template."""
    llm_on([json_reply(objective=1), json_reply(nothing=True)])
    t = await models.write_ticket("Add a setting.", FINDINGS, [])
    assert t.stub and t.objective == "Add a setting."


async def test_summarize_and_answer(llm_on: Callable[..., FakeLLM]) -> None:
    """A13: text jobs return the model's text."""
    llm_on(["One earlier decision affects this request."])
    assert await models.summarize_findings(FINDINGS) == "One earlier decision affects this request."
    llm_on([json_reply(text="Ana wrote it [e1].", evidenceIds=["e1", "zz"])])
    a = await models.write_answer("Who wrote it?", [models.EvidenceItem(id="e1", text="Ana")])
    assert a.text == "Ana wrote it [e1]." and a.evidenceIds == ["e1"] and not a.stub


async def test_agent_completion_tool_calls(llm_on: Callable[..., FakeLLM]) -> None:
    """B5 interface: agent_completion returns AgentTurn with parsed tool calls and tokens."""
    fake = llm_on(
        [
            {
                "tool_calls": [
                    {"id": "t1", "name": "search", "arguments": {"query": "paredit"}},
                    {"id": "t2", "name": "get_node", "arguments": "not json"},
                ]
            }
        ]
    )
    tools = [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}]
    turn = await models.agent_completion([{"role": "user", "content": "find paredit"}], tools)
    assert [c.name for c in turn.tool_calls] == ["search", "get_node"]
    assert turn.tool_calls[0].arguments == {"query": "paredit"}
    assert turn.tool_calls[1].arguments == {"_raw": "not json"}
    assert (
        turn.tokens == {"input": 50, "output": 20}
        and not turn.stub
        and turn.model == "groq/fake-agent"
    )
    assert fake.calls[0]["tools"] == tools and fake.calls[0]["tool_choice"] == "auto"
    llm_on([json_reply(seedIds=["a"], decisionIds=[], relatedWorkIds=[], notes="n")])
    final = await models.agent_completion([{"role": "user", "content": "done?"}], tools)
    assert final.tool_calls == [] and final.content and "seedIds" in final.content


def test_prompts_follow_voice_rules() -> None:
    """PRD 13.4: prompts shown to users carry the voice rules; no exclamation marks in prompt text."""
    from actron.models.jobs import PROMPTS

    names = {p.stem for p in PROMPTS.glob("*.md")}
    assert {
        "judgment",
        "decision_extraction",
        "questions",
        "ticket",
        "answer",
        "situation",
        "investigator",
        "procedure_extraction",
    } <= names
    for name in ("questions", "ticket", "answer", "situation"):
        text = (PROMPTS / f"{name}.md").read_text()
        assert "no exclamation marks" in text.lower() and "version:" in text
