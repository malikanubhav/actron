"""PostgreSQL tables (spec A, A2). SQLAlchemy 2 typed models; migrations in actron/db/migrations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slack_user_id: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    slack_team_id: Mapped[str | None] = mapped_column(Text, unique=True)
    graph_name: Mapped[str] = mapped_column(Text, unique=True)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    __tablename__ = "memberships"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, default="member", server_default="member")


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider"),
        CheckConstraint(
            "provider in ('github','slack','linear','code','slack_export')", name="provider_ck"
        ),
        CheckConstraint("status in ('connected','error','disconnected')", name="status_ck"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="connected")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_last4: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SyncCursor(Base):
    __tablename__ = "sync_cursors"
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint("mode in ('backfill','incremental')", name="mode_ck"),
        CheckConstraint("status in ('running','done','partial','failed')", name="run_status_ck"),
        Index("ix_sync_runs_ws_source", "workspace_id", "source", "started_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    errors: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    reason: Mapped[str | None] = mapped_column(Text)
    temporal_workflow_id: Mapped[str | None] = mapped_column(Text)
    temporal_run_id: Mapped[str | None] = mapped_column(Text)


class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (Index("ix_requests_ws_state", "workspace_id", "state"),)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="ui")
    requester_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    slack_channel: Mapped[str | None] = mapped_column(Text)
    slack_thread_ts: Mapped[str | None] = mapped_column(Text)
    slack_status_ts: Mapped[str | None] = mapped_column(Text)
    linear_issue_id: Mapped[str | None] = mapped_column(Text)
    pr_number: Mapped[int | None] = mapped_column(Integer)
    temporal_workflow_id: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class TicketRevision(Base):
    __tablename__ = "ticket_revisions"
    __table_args__ = (UniqueConstraint("request_id", "n"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    n: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    external_edit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    linear: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("kind in ('ticket','pr')", name="approval_kind_ck"),
        CheckConstraint("surface in ('slack','ui')", name="approval_surface_ck"),
        CheckConstraint("status in ('accepted','refused')", name="approval_status_ck"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_slack_id: Mapped[str | None] = mapped_column(Text)
    actor_name: Mapped[str | None] = mapped_column(Text)
    surface: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuildRun(Base):
    __tablename__ = "build_runs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text)
    branch: Mapped[str] = mapped_column(Text)
    base_sha: Mapped[str] = mapped_column(Text, default="")
    head_sha: Mapped[str | None] = mapped_column(Text)
    tests_passed: Mapped[int] = mapped_column(Integer, default=0)
    tests_failed: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    log_path: Mapped[str] = mapped_column(Text, default="")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index(
            "ux_events_request_seq",
            "request_id",
            "seq",
            unique=True,
            postgresql_where=sql_text("request_id IS NOT NULL"),
        ),
        Index("ix_events_ws_id", "workspace_id", "id"),
        CheckConstraint(
            "signal_status is null or signal_status in ('pending','sent')", name="signal_ck"
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    request_id: Mapped[str | None] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    seq: Mapped[int | None] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(Text, default="actron")
    surface: Mapped[str] = mapped_column(Text, default="system")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    signal_status: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str | None] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    tab: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(Text)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (Index("ix_model_calls_ws_created", "workspace_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    job: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    stub: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


_ = String  # kept for migrations that import it from here
