"""The investigator agent (spec B, B5): a tool-calling loop over the MCP graph tools.

The model (`MODEL_AGENT`, through `actron.models.agent_completion`) chooses which graph tools to call, at most
12 calls or 3 minutes. Each call goes through the in-process MCP client, so the server emits `tool.called`
and `tool.result`. The model ends with `{seedIds, decisionIds, relatedWorkIds, notes}`; ids that no tool
returned in this run are dropped (B-AC-24). The canonical findings are then built by `shared_query` from
the seed ids, so the output shape never depends on the model.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from actron.logging import get_logger

log = get_logger(__name__)

MAX_TOOL_CALLS = 12
MAX_SECONDS = 180.0
MAX_TOOL_RESULT_CHARS = 12000

FALLBACK_PROMPT = (
    "You investigate a software change request against the team's history graph. Use the tools; never "
    "state a fact without a node id a tool returned. At most 12 tool calls. When done, reply with one JSON "
    "object: {\"seedIds\": [...], \"decisionIds\": [...], \"relatedWorkIds\": [...], \"notes\": \"...\"}."
)


class AgentFailed(RuntimeError):
    """The agent could not produce findings (model error, timeout or no final JSON)."""


class ToolsClient(Protocol):
    async def function_schemas(self) -> list[dict[str, Any]]: ...

    async def call(self, name: str, args: Mapping[str, Any] | None = None) -> Any: ...


Complete = Callable[..., Awaitable[Any]]  # agent_completion(messages, tools, *, ws, request_id) -> AgentTurn


@dataclass
class AgentOutcome:
    seed_ids: list[str] = field(default_factory=list)
    decision_ids: list[str] = field(default_factory=list)
    related_ids: list[str] = field(default_factory=list)
    notes: str = ""
    tool_calls: int = 0
    tokens: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0})
    model: str = ""
    stub: bool = False
    dropped_ids: list[str] = field(default_factory=list)
    stopped_by_budget: bool = False


def system_prompt() -> str:
    try:
        from actron.models.jobs import prompt

        text = prompt("investigator")
    except Exception:
        return FALLBACK_PROMPT
    return re.sub(r"^<!--.*?-->\s*", "", text, flags=re.S)


def _user_message(text: str, kind: str) -> str:
    return (f"Request ({kind}):\n{text}\n\nInvestigate it with the graph tools, then reply with only the JSON "
            "object described in your instructions.")


def parse_final(content: str | None) -> dict[str, Any]:
    """Pull the findings JSON out of the model's last message (tolerates code fences and prose around it)."""
    if not content:
        raise AgentFailed("the agent ended without a findings JSON")
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidates = [fenced.group(1)] if fenced else []
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise AgentFailed("the agent's final message is not a JSON object")


def _ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in dict.fromkeys(value) if isinstance(v, str)]


def _turn_get(turn: Any, name: str, default: Any = None) -> Any:
    if isinstance(turn, Mapping):
        return turn.get(name, default)
    return getattr(turn, name, default)


def _call_parts(call: Any) -> tuple[str, str, dict[str, Any]]:
    cid = str(_turn_get(call, "id", "") or "")
    name = str(_turn_get(call, "name", "") or "")
    args = _turn_get(call, "arguments", {}) or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return cid, name, dict(args) if isinstance(args, Mapping) else {}


async def run_agent(
    text: str,
    kind: str,
    *,
    client: ToolsClient,
    returned_ids: set[str],
    complete: Complete,
    ws: str | None = None,
    request_id: str | None = None,
    max_calls: int = MAX_TOOL_CALLS,
    max_seconds: float = MAX_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> AgentOutcome:
    """Run the loop. `returned_ids` is the set the tool context fills with every node id a tool returned."""
    tools = await client.function_schemas()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": _user_message(text, kind)},
    ]
    out = AgentOutcome()
    deadline = clock() + max_seconds
    final: dict[str, Any] | None = None
    for _turn_no in range(max_calls + 4):
        budget_left = out.tool_calls < max_calls and clock() < deadline
        if not budget_left:
            out.stopped_by_budget = True
            messages.append({"role": "user", "content": "The tool budget is used up. Reply now with only the "
                                                        "JSON object."})
        try:
            turn = await complete(messages, tools if budget_left else [], ws=ws, request_id=request_id)
        except Exception as exc:
            raise AgentFailed(f"model call failed: {type(exc).__name__}: {exc}") from exc
        tokens = _turn_get(turn, "tokens", {}) or {}
        out.tokens["input"] += int(tokens.get("input", 0) or 0)
        out.tokens["output"] += int(tokens.get("output", 0) or 0)
        out.model = str(_turn_get(turn, "model", "") or out.model)
        out.stub = out.stub or bool(_turn_get(turn, "stub", False))
        calls = list(_turn_get(turn, "tool_calls", []) or [])
        if calls and budget_left:
            parsed = [_call_parts(c) for c in calls]
            messages.append({
                "role": "assistant",
                "content": _turn_get(turn, "content", None),
                "tool_calls": [{"id": cid, "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)}} for cid, name, args in parsed],
            })
            for cid, name, args in parsed:
                if out.tool_calls >= max_calls or clock() >= deadline:
                    result: Any = {"error": {"code": "budget", "message": "The tool budget is used up."}}
                else:
                    out.tool_calls += 1
                    result = await client.call(name, args)
                messages.append({"role": "tool", "tool_call_id": cid,
                                 "content": json.dumps(result, default=str)[:MAX_TOOL_RESULT_CHARS]})
            continue
        final = parse_final(_turn_get(turn, "content", None))
        break
    if final is None:
        raise AgentFailed("the agent did not finish")
    known = set(returned_ids)
    for key, attr in (("seedIds", "seed_ids"), ("decisionIds", "decision_ids"), ("relatedWorkIds", "related_ids")):
        wanted = _ids(final.get(key))
        kept = [i for i in wanted if i in known]
        out.dropped_ids.extend(i for i in wanted if i not in known)
        setattr(out, attr, kept)
    if out.dropped_ids:
        log.info("agent ids dropped (no tool returned them)", extra={"count": len(out.dropped_ids)})
    notes = final.get("notes")
    out.notes = notes if isinstance(notes, str) else ""
    return out


def filter_known(ids_in: Sequence[str], known: set[str]) -> list[str]:
    return [i for i in ids_in if i in known]
