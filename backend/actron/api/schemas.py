"""Pydantic request and response models for the frozen API contract (spec B, B.C7).

They exist so `/api/openapi.json` carries the exact shapes the frontend generates its types from.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

State = Literal["Investigating", "Needs your input", "Ticket ready", "Awaiting approval", "Building",
                "Needs attention", "PR ready for review", "Changes requested", "Done", "Cancelled"]
Label = Literal["conflict", "possible_conflict", "nothing_found", "clear"]
Kind = Literal["feature", "bug", "question"]
Surface = Literal["slack", "ui", "system"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class PersonRef(BaseModel):
    personId: str | None
    userId: str | None
    name: str
    avatarUrl: str | None


class EventEnvelope(BaseModel):
    id: int
    requestId: str | None
    seq: int | None
    type: str
    at: str
    actor: Literal["actron", "person", "slack"]
    surface: Surface
    payload: dict[str, Any]


class QuestionOption(_Out):
    value: str
    label: str
    note: str | None = None
    preselected: bool | None = None


class QuestionAnswer(BaseModel):
    value: str
    by: PersonRef
    surface: Surface
    at: str | None


class Question(BaseModel):
    questionId: str
    text: str
    kind: Literal["choice", "text"]
    options: list[QuestionOption]
    evidenceIds: list[str]
    required: bool
    answer: QuestionAnswer | None


class Constraint(BaseModel):
    text: str
    evidenceIds: list[str] = Field(default_factory=list)


class TestPlanItem(BaseModel):
    kind: Literal["existing", "new"] = "existing"
    target: str = ""
    command: str = ""


class TicketContent(BaseModel):
    objective: str = Field(min_length=1, max_length=500)
    context: str = Field(default="", max_length=4000)
    acceptanceCriteria: list[str] = Field(default_factory=list)
    constraintsToPreserve: list[Constraint] = Field(default_factory=list)
    affectedFunctions: list[str] = Field(default_factory=list)
    testPlan: list[TestPlanItem] = Field(default_factory=list)
    outOfScope: list[str] = Field(default_factory=list)
    targetBranch: str = ""


class LinearRef(BaseModel):
    issueId: str | None
    identifier: str | None
    url: str | None


class Revision(BaseModel):
    n: int
    hash: str
    content: dict[str, Any]
    createdBy: str
    createdAt: str | None
    linear: LinearRef | None
    externalEdit: bool


class Approval(BaseModel):
    id: str
    kind: Literal["ticket", "pr"]
    target: str
    status: Literal["accepted", "refused"]
    reason: str | None
    by: PersonRef
    surface: Literal["slack", "ui"]
    at: str | None


class Tokens(BaseModel):
    input: int
    output: int


class Build(BaseModel):
    id: str
    status: Literal["queued", "running", "passed", "failed", "stopped", "waiting_budget"]
    queuePosition: int | None
    branch: str
    baseSha: str
    headSha: str | None
    testsPassed: int
    testsFailed: int
    attempts: int
    startedAt: str | None
    finishedAt: str | None
    stopReason: str | None
    tokens: Tokens
    costUsd: float
    report: dict[str, Any] | None


class Pr(BaseModel):
    number: int
    url: str
    headSha: str
    state: Literal["open", "merged", "closed"]
    targetBranch: str


class LastEvent(BaseModel):
    type: str
    sentence: str
    at: str | None


class RequestSummary(BaseModel):
    id: str
    title: str
    kind: Kind
    state: State
    label: Label | None
    requester: PersonRef
    source: Literal["slack", "ui"]
    createdAt: str | None
    updatedAt: str | None
    lastEvent: LastEvent | None
    pipelineStep: int = Field(ge=1, le=6)
    needsYou: bool


class EvidenceSource(BaseModel):
    type: str
    id: str
    url: str | None
    author: str | None
    at: str | None


class Evidence(BaseModel):
    evidenceId: str
    role: Literal["conflict", "constraint", "impact", "similar_work", "owner", "test"]
    nodeId: str
    nodeType: str
    title: str
    quote: str | None
    source: EvidenceSource
    confidence: float
    tier: Literal["HIGH", "MEDIUM", "POSSIBLE"]
    path: list[str]


class SlackRef(BaseModel):
    channel: str
    threadTs: str
    permalink: str | None


class Investigation(BaseModel):
    mode: Literal["agent", "pipeline"]
    toolCalls: int
    tokens: Tokens
    costUsd: float
    stub: bool


class AnswerOut(BaseModel):
    text: str
    citations: list[Evidence]


AllowedAction = Literal["answer", "edit_ticket", "approve_ticket", "pr_feedback", "approve_pr", "close_pr",
                        "retry", "cancel"]


class RequestDetail(RequestSummary):
    text: str
    headline: str
    purpose: str
    slack: SlackRef | None
    findings: dict[str, Any] | None
    evidence: list[Evidence]
    questions: list[Question]
    revisions: list[Revision]
    currentRevision: dict[str, Any] | None
    approvals: list[Approval]
    builds: list[Build]
    pr: Pr | None
    investigation: Investigation | None
    outcome: Literal["approved", "answered", "cancelled", "closed"] | None
    answer: AnswerOut | None
    allowedActions: list[AllowedAction]
    memory: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None


class ActionResult(BaseModel):
    status: Literal["accepted", "refused", "pending", "duplicate"]
    reason: str | None
    eventId: int | None
    state: State | None


class RequestOut(BaseModel):
    request: RequestDetail


class Counts(BaseModel):
    needsYou: int
    running: int
    done: int


class RequestList(BaseModel):
    requests: list[RequestSummary]
    counts: Counts


class ResultOut(BaseModel):
    result: ActionResult


class RevisionResult(BaseModel):
    result: ActionResult
    revision: Revision | None


class RevisionDiff(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: int = Field(alias="from")
    to: int
    changes: list[dict[str, Any]]


class RevisionList(BaseModel):
    revisions: list[Revision]
    diffs: list[dict[str, Any]]


class ReplayOut(BaseModel):
    request: RequestDetail
    events: list[EventEnvelope]


class CreateRequestIn(BaseModel):
    text: str = Field(min_length=3, max_length=4000)
    kindHint: Kind | None = None


class AnswerIn(BaseModel):
    questionId: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=4000)


class RevisionIn(BaseModel):
    content: TicketContent


class ApprovalIn(BaseModel):
    kind: Literal["ticket", "pr"]
    revisionHash: str | None = Field(default=None, max_length=128)
    headSha: str | None = Field(default=None, max_length=128)


class FeedbackIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    headSha: str = Field(default="", max_length=128)


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class PrDiffFile(BaseModel):
    path: str
    status: str
    additions: int
    deletions: int
    patch: str


class PrDiff(BaseModel):
    files: list[PrDiffFile]
    headSha: str


class NotificationItem(BaseModel):
    id: str
    kind: Literal["needs_input", "awaiting_approval", "build_failed", "pr_ready"]
    title: str
    body: str
    requestId: str | None
    tab: str
    readAt: str | None
    createdAt: str | None


class NotificationList(BaseModel):
    notifications: list[NotificationItem]
    unread: int
