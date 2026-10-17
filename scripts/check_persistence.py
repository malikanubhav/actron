#!/usr/bin/env python3
"""Verify the checked-in deployment with its own temporary Compose project/volume.

This creates a synthetic graph on localhost:6390, confirms AOF is actually enabled,
replaces the container while retaining the volume, checks the graph survived, and
removes only its uniquely named project. Existing Actron resources are untouched.
Run from the repository: uv run python scripts/check_persistence.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path

from actron.graph import FalkorStore


def check_persistence(compose: Path, port: int) -> dict[str, str]:
    project = "actron-persistence-" + uuid.uuid4().hex[:16]
    environment = {**os.environ, "FALKORDB_PORT": str(port)}
    command = ["docker", "compose", "--project-name", project, "--file", str(compose)]

    def run(*arguments: str) -> str:
        result = subprocess.run(
            [*command, *arguments],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            raise RuntimeError(
                "Compose command failed: "
                + " ".join(arguments)
                + "\n"
                + result.stdout
                + result.stderr
            )
        return result.stdout.strip()

    try:
        run("config", "--quiet")
        run("up", "--detach", "--wait", "--wait-timeout", "45", "falkordb")
        store = FalkorStore(f"redis://127.0.0.1:{port}/0", "persistence_smoke")
        settings: dict[str, str] = store.redis.execute_command("CONFIG GET", "appendonly", "dir")
        if settings.get("appendonly") != "yes":
            raise RuntimeError("Deployment did not enable AOF; container argv may be ignored")
        container = run("ps", "--quiet", "falkordb")
        inspected = subprocess.run(
            ["docker", "inspect", container], check=True, capture_output=True, text=True, timeout=15
        )
        mounts = json.loads(inspected.stdout)[0]["Mounts"]
        if not any(
            mount["Type"] == "volume" and mount["Destination"] == settings["dir"]
            for mount in mounts
        ):
            raise RuntimeError("Actual FalkorDB data directory is not on a named volume")
        marker = {"id": project, "meaning": "Observed persisted graph across container replacement"}
        store.put("PersistenceCheck", project, marker)
        if store.get("PersistenceCheck", project) != marker:
            raise RuntimeError("Initial graph write was not readable")
        store.redis.close()
        run("stop", "--timeout", "10", "falkordb")
        run("rm", "--force", "falkordb")
        run("up", "--detach", "--wait", "--wait-timeout", "45", "falkordb")
        recovered = FalkorStore(f"redis://127.0.0.1:{port}/0", "persistence_smoke")
        try:
            if recovered.get("PersistenceCheck", project) != marker:
                raise RuntimeError("Persisted graph was lost when the container was replaced")
            recovered_settings: dict[str, str] = recovered.redis.execute_command(
                "CONFIG GET", "appendonly"
            )
            if recovered_settings.get("appendonly") != "yes":
                raise RuntimeError("Replacement container did not retain AOF configuration")
        finally:
            recovered.redis.close()
        return {
            "status": "passed",
            "project": project,
            "appendonly": "yes",
            "data_directory": str(settings["dir"]),
            "proof": "graph survived container replacement",
        }
    finally:
        # Project names are generated here, never accepted from user input or env.
        # This cannot tear down another running server/project or its data volume.
        run("down", "--volumes", "--remove-orphans", "--timeout", "10")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose", type=Path, default=Path(__file__).resolve().parents[1] / "compose.yaml"
    )
    parser.add_argument("--port", type=int, default=6390)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    print(json.dumps(check_persistence(args.compose.resolve(), args.port), indent=2))


if __name__ == "__main__":
    main()
