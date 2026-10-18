"""Backups (spec B, B12a): the compose backup job produces a dump that restores into a scratch database (B-AC-87).

Runs `infra/postgres/backup.sh --once` in a throwaway `postgres:16.15` container on the compose network, then
restores the `actron` dump with `pg_restore` into a new database and checks the tables are there.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from actron.config import REPO_ROOT

pytestmark = pytest.mark.integration
IMAGE = "postgres:16.15"


def _docker(*args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _network() -> str | None:
    out = _docker("inspect", "actron-postgres-1", "--format", "{{json .NetworkSettings.Networks}}")
    if out.returncode != 0:
        return None
    nets = json.loads(out.stdout or "{}")
    return next(iter(nets), None)


def test_backup_restores(tmp_path: Path) -> None:
    """B-AC-87: a fresh dump of `actron` restores into a scratch database with the app tables."""
    if shutil.which("docker") is None:
        pytest.skip("docker is not available")
    network = _network()
    if network is None:
        pytest.skip("the compose PostgreSQL container is not running")
    backups = tmp_path / "backups"
    backups.mkdir()
    backups.chmod(0o777)
    script = REPO_ROOT / "infra" / "postgres" / "backup.sh"
    env = ["-e", "PGHOST=postgres", "-e", "PGUSER=actron", "-e", "PGPASSWORD=actron"]
    run = _docker("run", "--rm", "--network", network, *env, "-v", f"{backups}:/backups",
                  "-v", f"{script}:/backup.sh:ro", IMAGE, "sh", "/backup.sh", "--once")
    assert run.returncode == 0, run.stderr
    dumps = sorted(backups.glob("actron-*.dump"))
    assert dumps, run.stdout
    scratch = f"w6_restore_{uuid.uuid4().hex[:8]}"
    try:
        create = _docker("run", "--rm", "--network", network, *env, IMAGE, "createdb", scratch)
        assert create.returncode == 0, create.stderr
        restore = _docker("run", "--rm", "--network", network, *env, "-v", f"{backups}:/backups", IMAGE,
                          "pg_restore", "--no-owner", f"--dbname={scratch}", f"/backups/{dumps[-1].name}")
        assert restore.returncode == 0, restore.stderr
        tables = _docker("run", "--rm", "--network", network, *env, IMAGE, "psql", "-d", scratch, "-At", "-c",
                         "SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables "
                         "WHERE schemaname = 'public'")
        names = set(tables.stdout.strip().split(","))
        assert {"requests", "events", "workspaces", "ticket_revisions", "approvals"} <= names
    finally:
        _docker("run", "--rm", "--network", network, *env, IMAGE, "dropdb", "--if-exists", scratch)
