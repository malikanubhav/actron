"""Typed inputs and outputs of the model layer (spec A, A13)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Provider = Literal["jev", "llm", "stub"]


class Judgment(BaseModel):
    """One answer to one narrow question, from Jev, the LLM fallback or a stub."""

    job: str
    answer: Any
    probability: float | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    model: str
    provider: Provider
    cached: bool = False
    stub: bool = False


class Candidate(BaseModel):
    """A code or feature node that a text might be about (J3)."""

    kind: Literal["function", "class", "file", "feature"]
    name: str
    path: str | None = None
    signature: str | None = None
    docstring: str | None = None
    id: str | None = None  # node id, never sent to the model


class CandidateSummary(BaseModel):
    """One seed candidate for a request (J5)."""

    id: str
    summary: str


class DecisionView(BaseModel):
    """What J6 sees of a decision."""

    statement: str
    quote: str
    status: Literal["approved", "proposed", "superseded"]


class DecisionExtraction(BaseModel):
    """Result of `extract_decision` (A12.4). `quote` is an exact substring of the source text."""

    is_decision: bool
    statement: str
    quote: str
    scope: str = ""
    status_hint: Literal["decided", "proposed"] = "proposed"
    quote_span: tuple[int, int] = (0, 0)
    model: str = ""
    provider: Provider = "llm"
    stub: bool = False


class QuestionOption(BaseModel):
    value: str
    label: str


class Question(BaseModel):
    """A clarifying question (spec B, B6)."""

    questionId: str
    text: str
    kind: Literal["choice", "text"] = "choice"
    options: list[QuestionOption] | None = None
    evidenceIds: list[str] = Field(default_factory=list)
    required: bool = True


class ConstraintItem(BaseModel):
    text: str
    evidenceIds: list[str] = Field(default_factory=list)


class TestPlanItem(BaseModel):
    kind: Literal["existing", "new"] = "existing"
    target: str
    command: str = ""


class Ticket(BaseModel):
    """Ticket content (spec B, B.C5) without `requestId`/`revision`, which the flow adds."""

    objective: str
    context: str
    acceptanceCriteria: list[str] = Field(default_factory=list)
    constraintsToPreserve: list[ConstraintItem] = Field(default_factory=list)
    affectedFunctions: list[str] = Field(default_factory=list)
    testPlan: list[TestPlanItem] = Field(default_factory=list)
    outOfScope: list[str] = Field(default_factory=list)
    targetBranch: str = "main"
    stub: bool = Field(default=False, exclude=True)


class EvidenceItem(BaseModel):
    """One piece of evidence for a Q&A answer."""

    id: str
    type: str = ""
    text: str = ""
    url: str | None = None


class Answer(BaseModel):
    """A Q&A answer (`write_answer`)."""

    text: str
    evidenceIds: list[str] = Field(default_factory=list)
    stub: bool = False


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentTurn(BaseModel):
    """One tool-calling turn of the investigator model."""

    tool_calls: list[ToolCall] = Field(default_factory=list)
    content: str | None = None
    tokens: dict[str, int] = Field(default_factory=lambda: {"input": 0, "output": 0})
    stub: bool = False
    model: str = ""


class ModelError(RuntimeError):
    """Base class for model layer errors."""


class ModelUnavailable(ModelError):
    """No key or no model is configured for this job."""


class InvalidModelOutput(ModelError):
    """The model answered, but not in the required shape."""
