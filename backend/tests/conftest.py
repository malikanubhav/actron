"""Shared fixtures. Integration fixtures use the compose stack (`make up-deps`) and skip when it is down.

- `ontology`: the real ontology files (session scope).
- `graph`: a fresh FalkorDB graph per test (`actron_test_<random>`), dropped afterwards.
- `db_url`: a per-session PostgreSQL database migrated to head; `db_session` gives a sync Session.
- `redis_client`: Redis database 15, flushed before each test.
"""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("ACTRON_ENV", "test")
# The budget tests assume the shipped default. A developer's .env may cap spend lower (an environment variable
# outranks .env), so pin the default here instead of reading whatever the local file says.
os.environ.setdefault("ACTRON_DAILY_MODEL_BUDGET_USD", "20")
# Importing litellm in DEV mode loads the repository's .env into os.environ, which would bring the credentials and
# local settings removed below straight back for every test that runs afterwards.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
# Each parallel workstream uses its own Redis database (ACTRON_TEST_REDIS_DB) so flushes never collide.
_REDIS_DB = os.environ.get("ACTRON_TEST_REDIS_DB", "15")
os.environ["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/0").rsplit("/", 1)[0] + f"/{_REDIS_DB}"

from actron.config import REPO_ROOT, Settings, get_settings  # noqa: E402

# The suite assumes a key-free environment: no provider is connected and models answer as stubs (tests talk to
# fakes). A developer's .env may hold real keys; tests that clear a key from the environment and reload settings
# would read it straight back from that file. So settings load from a copy of .env without the credential and
# machine-specific lines (store URLs, secrets and ports stay). Live checks against real providers belong to scripts/live_smoke.sh.
_LOCAL_ONLY = frozenset(
    {
        "SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN", "SLACK_CHANNELS", "SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET",
        "GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_FORK", "GITHUB_UPSTREAM", "GITHUB_WEBHOOK_SECRET",
        "LINEAR_API_KEY", "LINEAR_TEAM_ID",
        "TYPESAFE_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "DEEPSEEK_API_KEY",
        "MODEL_DECISION", "MODEL_WRITING", "MODEL_AGENT", "MODEL_CODING", "LITELLM_FALLBACKS",
        "ACTRON_BOT_NAME", "ACTRON_BOT_EMAIL",
        # Not a credential, but local too: links in Slack message snapshots are built from it (a dev tunnel on one machine).
        "ACTRON_PUBLIC_URL",
    }
)


def _key_free_env_files() -> tuple[str, ...]:
    import atexit
    import shutil
    import tempfile

    source = REPO_ROOT / ".env"
    if not source.exists():
        return ()
    kept = [line for line in source.read_text().splitlines() if line.split("=", 1)[0].strip() not in _LOCAL_ONLY]
    folder = Path(tempfile.mkdtemp(prefix="actron-test-env-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    (folder / ".env").write_text("\n".join(kept) + "\n")
    return (str(folder / ".env"),)


Settings.model_config["env_file"] = _key_free_env_files()
from actron.graph.ontology import Ontology, load_ontology  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _port_open(url: str, default_port: int) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or default_port
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def ontology() -> Ontology:
    return load_ontology(REPO_ROOT / "ontology")


@pytest.fixture(scope="session")
def falkordb_url() -> str:
    url = get_settings().FALKORDB_URL
    if not _port_open(url, 6379):
        pytest.skip("FalkorDB is not running (make up-deps)")
    return url


@pytest.fixture
def graph(falkordb_url: str, ontology: Ontology) -> Iterator[Any]:
    from actron.graph.store import GraphStore

    name = f"actron_test_{uuid.uuid4().hex[:10]}"
    store = GraphStore(falkordb_url, name, ontology, workspace_id=name)
    try:
        yield store
    finally:
        store.drop()
        store.close()


@pytest.fixture
def indexed_graph(graph: Any, ontology: Ontology) -> Any:
    from actron.graph.ontology import ensure_indexes

    ensure_indexes(graph, ontology)
    return graph


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    """A fresh database per test session, migrated to head."""
    from sqlalchemy import create_engine, text

    base = get_settings().DATABASE_URL
    if not _port_open(base.replace("postgresql+psycopg://", "postgresql://"), 5432):
        pytest.skip("PostgreSQL is not running (make up-deps)")
    name = f"actron_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = base.rsplit("/", 1)[0] + "/" + name
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "backend" / "actron" / "db" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "actron" / "db" / "migrations"))
    cfg.cmd_opts = None
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    from actron.db.session import reset_engines

    reset_engines()
    command.upgrade(cfg, "head")
    try:
        yield url
    finally:
        reset_engines()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def db_session(db_url: str) -> Iterator[Any]:
    from actron.db.session import session_scope

    with session_scope(db_url) as session:
        yield session


@pytest.fixture
def redis_url() -> str:
    url = get_settings().REDIS_URL
    if not _port_open(url, 6379):
        pytest.skip("Redis is not running (make up-deps)")
    return url


@pytest.fixture
def redis_client(redis_url: str) -> Iterator[Any]:
    import redis

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()


@pytest.fixture(scope="session")
def temporal_address() -> str:
    addr = get_settings().TEMPORAL_ADDRESS
    host, _, port = addr.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=1):
            return addr
    except OSError:
        pytest.skip("Temporal is not running (make up-deps)")
