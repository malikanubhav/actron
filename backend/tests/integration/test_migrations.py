"""A-AC-6 (migrations up, down, up), A-AC-7 (secrets in the database), models match migrations."""

from __future__ import annotations

import argparse
import subprocess
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from actron.config import REPO_ROOT, get_settings
from actron.db.crypto import SecretDecryptError, decrypt_secret, encrypt_secret, last4
from actron.db.models import Base, Connection, Workspace
from actron.db.session import session_scope

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "users",
    "workspaces",
    "memberships",
    "connections",
    "sync_cursors",
    "sync_runs",
    "requests",
    "ticket_revisions",
    "approvals",
    "build_runs",
    "events",
    "notifications",
    "drafts",
    "idempotency_keys",
    "model_calls",
}


def config_for(url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "backend" / "actron" / "db" / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend" / "actron" / "db" / "migrations")
    )
    cfg.cmd_opts = argparse.Namespace(x=[f"url={url}"])
    return cfg


@pytest.fixture
def empty_db(db_url: str) -> Iterator[str]:
    """A brand new empty database (not migrated)."""
    base = get_settings().DATABASE_URL
    name = f"actron_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield base.rsplit("/", 1)[0] + "/" + name
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_up_down_up_on_empty_database_a_ac_6(empty_db: str) -> None:
    """A-AC-6"""
    cfg = config_for(empty_db)
    command.upgrade(cfg, "head")
    assert tables(empty_db) == EXPECTED_TABLES
    command.downgrade(cfg, "base")
    assert tables(empty_db) == set()
    command.upgrade(cfg, "head")
    assert tables(empty_db) == EXPECTED_TABLES


def test_upgrade_is_idempotent_a_ac_6(empty_db: str) -> None:
    """A-AC-6: running `upgrade head` again changes nothing."""
    cfg = config_for(empty_db)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    assert tables(empty_db) == EXPECTED_TABLES


def test_models_match_migrations_a_ac_6(empty_db: str) -> None:
    """A-AC-6: a migrated database has no drift from the SQLAlchemy models."""
    command.upgrade(config_for(empty_db), "head")
    engine = create_engine(empty_db)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    assert diff == []


def test_events_unique_per_request_seq(db_session: Any) -> None:
    """A-AC-9 (schema side): (request_id, seq) is unique when request_id is set."""
    ws = f"ws-{uuid.uuid4().hex[:6]}"
    db_session.execute(
        text("INSERT INTO workspaces (id, name, graph_name) VALUES (:i, 'n', :g)"),
        {"i": ws, "g": ws},
    )
    db_session.execute(
        text(
            "INSERT INTO requests (id, workspace_id, kind, title, text, state, source, temporal_workflow_id) "
            "VALUES ('req_a', :w, 'feature', 't', 't', 'new', 'ui', 'wf')"
        ),
        {"w": ws},
    )
    db_session.execute(
        text(
            "INSERT INTO events (workspace_id, request_id, seq, type, actor, surface, payload) "
            "VALUES (:w, 'req_a', 1, 'x', 'a', 's', '{}')"
        ),
        {"w": ws},
    )
    db_session.commit()
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO events (workspace_id, request_id, seq, type, actor, surface, payload) "
                "VALUES (:w, 'req_a', 1, 'x', 'a', 's', '{}')"
            ),
            {"w": ws},
        )
    db_session.rollback()
    # Workspace-level events (request_id null) may repeat seq.
    for _ in range(2):
        db_session.execute(
            text(
                "INSERT INTO events (workspace_id, request_id, seq, type, actor, surface, payload) "
                "VALUES (:w, NULL, NULL, 'y', 'a', 's', '{}')"
            ),
            {"w": ws},
        )
    db_session.commit()
    db_session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": ws})
    db_session.commit()


def test_connection_check_constraints(db_session: Any) -> None:
    ws = f"ws-{uuid.uuid4().hex[:6]}"
    db_session.add(Workspace(id=ws, name="n", graph_name=ws))
    db_session.commit()
    db_session.add(Connection(workspace_id=ws, provider="bitbucket", status="connected"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    db_session.add(Connection(workspace_id=ws, provider="github", status="weird"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    db_session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": ws})
    db_session.commit()


def test_secret_is_unreadable_in_dump_and_decrypts_with_key_a_ac_7(db_url: str) -> None:
    """A-AC-7: a stored connection secret is not in the database dump; decrypts with the key only."""
    key = Fernet.generate_key().decode()
    other = Fernet.generate_key().decode()
    token = "ghp_" + uuid.uuid4().hex + "ZZZZ"
    ws = f"ws-{uuid.uuid4().hex[:6]}"
    with session_scope(db_url) as session:
        session.add(Workspace(id=ws, name="n", graph_name=ws))
        session.flush()
        session.add(
            Connection(
                workspace_id=ws,
                provider="github",
                status="connected",
                config={"repo": "a/b"},
                secret_encrypted=encrypt_secret({"token": token}, key),
                secret_last4=last4(token),
            )
        )
    dump = subprocess.run(
        [
            "docker",
            "exec",
            "actron-postgres-1",
            "pg_dump",
            "-U",
            "actron",
            "--data-only",
            "-t",
            "connections",
            db_url.rsplit("/", 1)[1],
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert dump.returncode == 0, dump.stderr
    assert "connections" in dump.stdout
    assert token not in dump.stdout
    assert token[-4:] in dump.stdout  # secret_last4 is the only visible part
    with session_scope(db_url) as session:
        row = session.query(Connection).filter_by(workspace_id=ws).one()
        assert row.secret_last4 == token[-4:]
        assert decrypt_secret(row.secret_encrypted, key) == {"token": token}
        with pytest.raises(SecretDecryptError):
            decrypt_secret(row.secret_encrypted, other)
        session.delete(row)
        session.query(Workspace).filter_by(id=ws).delete()
