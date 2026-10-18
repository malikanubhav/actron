"""Procedures (spec A, A12.6, bonus): how changes are made in each area of the code.

One `Procedure` per top-level directory touched by merged PRs: `testCommand` = the most common test command in
those PRs' descriptions (else in CI workflow files), `coChangedPaths` = path pairs changed together in >= 30% of
the area's merged PRs, `steps` from the template (or `MODEL_WRITING` when available), `LEARNED_FROM_PR` to the
PRs. Texts that state how changes are made (Slack messages, PR templates and descriptions) add steps and a
command through `extract_procedure`, linked with `LEARNED_FROM_TEXT`.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from actron import models
from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow
from actron.linking.classify import Classification
from actron.linking.common import TextNode, load_texts

CO_CHANGE_SHARE = 0.3
MIN_PRS_FOR_PAIRS = 2
MAX_PAIRS = 10
MAX_SOURCE_PRS = 20
RUNNERS = (
    r"(?:npm|npx|yarn|pnpm|bun|node|pytest|python -m pytest|uv run|make|go test|cargo test|lein|clojure|clj|bb|"
    r"mvn|gradle|\./gradlew|tox|nox)"
)
COMMAND = re.compile(rf"(?m)(?:`|^\s*\$\s+|^\s*-?\s*run:\s*)({RUNNERS}[^`\n]*?)(?:`|\s*$)")
TEXT_KINDS = frozenset({"status_update", "request"})
STEP_LINE = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$")


@dataclass
class ProcedureReport:
    procedures: int = 0
    learned_from_pr: int = 0
    learned_from_text: int = 0
    areas: list[str] = field(default_factory=list)


def procedure_id(area: str) -> str:
    return ids.procedure("repository root" if area == "." else area)


def area_of(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "."


def commands_in(text: str) -> list[str]:
    out = []
    for m in COMMAND.finditer(text or ""):
        cmd = m.group(1).strip().rstrip(".")
        if "test" in cmd or cmd.startswith(("pytest", "make", "go test", "cargo test")):
            out.append(cmd)
    return out


def co_changed(pr_paths: list[set[str]], share: float = CO_CHANGE_SHARE) -> list[str]:
    if len(pr_paths) < MIN_PRS_FOR_PAIRS:
        return []
    counts: Counter[tuple[str, str]] = Counter()
    for paths in pr_paths:
        for a, b in combinations(sorted(paths), 2):
            counts[(a, b)] += 1
    need = share * len(pr_paths)
    pairs = [(n, a, b) for (a, b), n in counts.items() if n >= need and n >= 2]
    pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [f"{a} <-> {b}" for _, a, b in pairs[:MAX_PAIRS]]


def template_steps(area: str, command: str | None, pairs: list[str]) -> list[str]:
    steps = [f"Make the change under {area if area != '.' else 'the repository root'}."]
    for pair in pairs[:3]:
        a, b = pair.split(" <-> ")
        steps.append(f"When {a} changes, check {b} too.")
    if command:
        steps.append(f"Run {command} before opening a pull request.")
    return steps


def heuristic_procedure(text: str) -> dict[str, Any] | None:
    """Deterministic fallback when no LLM is available: numbered or bulleted steps plus a test command."""
    steps = [s for s in STEP_LINE.findall(text) if len(s) > 3]
    cmds = commands_in(text)
    if len(steps) < 2 or not cmds:
        return None
    return {"area": "", "steps": steps[:12], "testCommand": cmds[0]}


def _component_for(store: GraphStore, area: str) -> tuple[str, str] | None:
    rows = store.query(
        "MATCH (c:CodeComponent) WHERE c.path = $p RETURN c.id AS id LIMIT 1",
        {"p": area},
        read_only=True,
    )
    return ("CodeComponent", str(rows[0]["id"])) if rows else None


def learn_from_prs(store: GraphStore) -> ProcedureReport:
    report = ProcedureReport()
    rows = store.query(
        "MATCH (p:GithubPullRequest)-[:CHANGES_FILE]->(f:GithubPullRequestFile) WHERE p.merged = true "
        "RETURN p.id AS pr, p.body AS body, p.mergedAt AS at, collect(f.path) AS paths",
        read_only=True,
    )
    ci = store.query(
        "MATCH (f:CodeFile) WHERE f.path STARTS WITH '.github/workflows/' RETURN f.text AS text",
        read_only=True,
    )
    ci_cmds = Counter(c for r in ci for c in commands_in(str(r.get("text") or "")))
    by_area: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        paths = [str(p) for p in r["paths"]]
        for area in sorted({area_of(p) for p in paths}):
            by_area[area].append(
                {
                    "pr": str(r["pr"]),
                    "body": str(r.get("body") or ""),
                    "at": r.get("at") or "",
                    "paths": {p for p in paths if area_of(p) == area},
                }
            )
    for area, prs in sorted(by_area.items()):
        if area.startswith("."):
            continue
        cmds = Counter(c for pr in prs for c in commands_in(pr["body"]))
        command = (cmds or ci_cmds).most_common(1)[0][0] if (cmds or ci_cmds) else None
        pairs = co_changed([pr["paths"] for pr in prs])
        pid = procedure_id(area)
        existing = store.get_node(pid) or {}
        store.upsert_nodes(
            "Procedure",
            [
                {
                    "id": pid,
                    "title": f"Changing {area}",
                    "area": area,
                    "testCommand": existing.get("testCommand") or command,
                    "coChangedPaths": pairs or None,
                    "steps": existing.get("steps") or template_steps(area, command, pairs),
                    "confidence": round(min(1.0, len(prs) / 10), 2),
                }
            ],
        )
        report.procedures += 1
        report.areas.append(area)
        recent = sorted(prs, key=lambda p: str(p["at"]), reverse=True)[:MAX_SOURCE_PRS]
        report.learned_from_pr += store.upsert_links(
            "LEARNED_FROM_PR",
            "Procedure",
            "GithubPullRequest",
            [LinkRow(pid, p["pr"], {"method": "inferred", "confidence": 0.8}) for p in recent],
        ).created
        comp = _component_for(store, area)
        if comp:
            store.upsert_links(
                "APPLIES_TO",
                "Procedure",
                comp[0],
                [LinkRow(pid, comp[1], {"method": "structural", "confidence": 1.0})],
            )
    return report


def _is_procedure_text(text: TextNode) -> bool:
    if text.label == "CodeDocument":
        return "pull_request_template" in str(text.props.get("path") or "").lower()
    return text.label in ("SlackMessage", "GithubPullRequest", "LinearComment", "LinearIssue")


async def learn_from_texts(
    store: GraphStore,
    text_ids: list[str],
    classes: dict[str, Classification],
    *,
    ws: str | None = None,
) -> ProcedureReport:
    report = ProcedureReport()
    for text in load_texts(store, text_ids, include_deleted=False):
        if not _is_procedure_text(text):
            continue
        c = classes.get(text.id)
        if (
            c is not None
            and not c.stub
            and c.kind not in TEXT_KINDS
            and text.label != "CodeDocument"
        ):
            continue
        found = await models.extract_procedure(text.text, ws=ws)
        if found is None:
            found = heuristic_procedure(text.text)
        if found is None:
            continue
        area = found["area"].strip().strip("/") or "."
        pid = procedure_id(area)
        existing = store.get_node(pid) or {}
        store.upsert_nodes(
            "Procedure",
            [
                {
                    "id": pid,
                    "title": existing.get("title")
                    or f"Changing {area if area != '.' else 'the repository'}",
                    "area": area,
                    "steps": found["steps"] or existing.get("steps"),
                    "testCommand": found.get("testCommand") or existing.get("testCommand"),
                    "confidence": existing.get("confidence") or 0.6,
                }
            ],
        )
        report.learned_from_text += store.upsert_links(
            "LEARNED_FROM_TEXT",
            "Procedure",
            text.label,
            [
                LinkRow(
                    pid,
                    text.id,
                    {
                        "method": "extracted",
                        "confidence": 0.7,
                        "sourceRef": text.id,
                        "quote": text.text[:300],
                    },
                )
            ],
        ).created
        report.procedures += 1
        report.areas.append(area)
    return report
