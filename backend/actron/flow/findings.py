"""Findings: the shared-query output (PROMPT appendix D, spec B, B.C3) and the evidence and question shapes (B.C7).

Field names are camelCase on purpose: these models serialise straight to the frozen JSON contract.
Every list item carries `path`, the node ids from the request node to the item (B.C3).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Label = Literal["conflict", "possible_conflict", "nothing_found", "clear"]
ConflictLabel = Literal["conflict", "possible_conflict", "none"]
DecisionStatus = Literal["approved", "proposed", "superseded"]
EvidenceRole = Literal["conflict", "constraint", "impact", "similar_work", "owner", "test"]
Tier = Literal["HIGH", "MEDIUM", "POSSIBLE"]
Mode = Literal["agent", "pipeline"]

# B.C3 list limits.
MAX_SEEDS = 10
MAX_DECISIONS = 15
MAX_RELATED = 15
MAX_CALLERS = 50
MAX_OWNERS = 5
MAX_GRAPH_NODES = 300


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SeedItem(_Model):
    id: str
    type: str
    score: float
    path: list[str] = Field(default_factory=list)


class SourceRef(_Model):
    id: str
    type: str
    url: str | None = None


class Conflict(_Model):
    label: ConflictLabel = "none"
    probability: float = 0.0


class DecisionItem(_Model):
    id: str
    statement: str
    status: DecisionStatus
    quote: str
    source: SourceRef | None = None
    conflict: Conflict = Field(default_factory=Conflict)
    path: list[str] = Field(default_factory=list)
    decidedAt: str | None = None


class RelatedWorkItem(_Model):
    id: str
    type: str
    title: str
    state: str | None = None
    url: str | None = None
    path: list[str] = Field(default_factory=list)
    at: str | None = None


class CallerItem(_Model):
    id: str
    depth: int
    path: list[str] = Field(default_factory=list)


class TestItem(_Model):
    id: str
    path: list[str] = Field(default_factory=list)


class CriticalityItem(_Model):
    id: str
    percentile: float
    path: list[str] = Field(default_factory=list)


class Impact(_Model):
    callers: list[CallerItem] = Field(default_factory=list)
    tests: list[TestItem] = Field(default_factory=list)
    criticality: list[CriticalityItem] = Field(default_factory=list)


class OwnerItem(_Model):
    personId: str | None
    name: str
    basis: list[str] = Field(default_factory=list)
    score: float
    path: list[str] = Field(default_factory=list)


class ProcedureItem(_Model):
    id: str
    testCommand: str | None = None
    path: list[str] = Field(default_factory=list)


class GraphNodeBrief(_Model):
    id: str
    type: str
    label: str


class GraphEdge(_Model):
    from_: str = Field(alias="from")
    to: str
    type: str


class FindingsGraph(_Model):
    nodes: list[GraphNodeBrief] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class Findings(_Model):
    requestId: str
    seeds: list[SeedItem] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)
    relatedWork: list[RelatedWorkItem] = Field(default_factory=list)
    impact: Impact = Field(default_factory=Impact)
    owners: list[OwnerItem] = Field(default_factory=list)
    procedures: list[ProcedureItem] = Field(default_factory=list)
    label: Label = "nothing_found"
    graph: FindingsGraph = Field(default_factory=FindingsGraph)

    def to_json(self) -> dict[str, Any]:
        """The appendix D JSON (aliases applied, so graph edges use `from`)."""
        return self.model_dump(by_alias=True, mode="json")

    def node_ids(self) -> set[str]:
        """Every node id that appears anywhere in the findings (items and paths)."""
        out: set[str] = {self.requestId}
        for seed in self.seeds:
            out.add(seed.id)
            out.update(seed.path)
        for d in self.decisions:
            out.add(d.id)
            out.update(d.path)
            if d.source:
                out.add(d.source.id)
        for r in self.relatedWork:
            out.add(r.id)
            out.update(r.path)
        for c in self.impact.callers:
            out.add(c.id)
            out.update(c.path)
        for t in self.impact.tests:
            out.add(t.id)
            out.update(t.path)
        for k in self.impact.criticality:
            out.add(k.id)
        for o in self.owners:
            if o.personId:
                out.add(o.personId)
            out.update(o.path)
        for p in self.procedures:
            out.add(p.id)
            out.update(p.path)
        return out


class EvidenceSource(_Model):
    type: str
    id: str
    url: str | None = None
    author: str | None = None
    at: str | None = None


class Evidence(_Model):
    """One piece of evidence shown in the UI and Slack (B.C7). `evidenceId` is the node id."""

    evidenceId: str
    role: EvidenceRole
    nodeId: str
    nodeType: str
    title: str
    quote: str | None = None
    source: EvidenceSource
    confidence: float
    tier: Tier
    path: list[str] = Field(default_factory=list)


class QuestionOption(_Model):
    value: str
    label: str
    note: str | None = None
    preselected: bool | None = None


class Question(_Model):
    questionId: str
    text: str
    kind: Literal["choice", "text"] = "choice"
    options: list[QuestionOption] = Field(default_factory=list)
    evidenceIds: list[str] = Field(default_factory=list)
    required: bool = True


class NodeBrief(_Model):
    """Extra facts about a node that the findings do not carry (author, time), used to build evidence."""

    id: str
    type: str
    title: str
    url: str | None = None
    author: str | None = None
    at: str | None = None
    quote: str | None = None
    confidence: float | None = None


class Tokens(_Model):
    input: int = 0
    output: int = 0


class InvestigationResult(_Model):
    findings: Findings
    label: Label
    summary: str
    mode: Mode
    tool_calls: int = 0
    tokens: Tokens = Field(default_factory=Tokens)
    cost_usd: float = 0.0
    stub: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    investigation_id: str | None = None
    fallback_reason: str | None = None


def tier_for(confidence: float) -> Tier:
    if confidence >= 0.8:
        return "HIGH"
    if confidence >= 0.5:
        return "MEDIUM"
    return "POSSIBLE"


def graph_label(label: Label) -> ConflictLabel:
    """`Investigation.conflictLabel` uses the ontology's values: nothing_found and clear both map to none (B5)."""
    if label == "conflict":
        return "conflict"
    if label == "possible_conflict":
        return "possible_conflict"
    return "none"


def findings_json_schema() -> dict[str, Any]:
    return Findings.model_json_schema(by_alias=True)
