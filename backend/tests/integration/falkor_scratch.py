"""A throwaway FalkorDB container for tests that restart the server or create unique constraints.

Same pinned image and settings as compose, a fixed random local port and a fresh volume. Tests never
restart the shared compose service: on v4.22.1 a restart after a constrained graph was deleted leaves
the shared server unable to start (docs/falkordb.md, limitation 12).
"""

from __future__ import annotations

import socket
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator

import pytest
import redis

IMAGE = "falkordb/falkordb:v4.22.1"
FALKORDB_ARGS = (
    "THREAD_COUNT 8 TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 15000 MAX_QUEUED_QUERIES 2000 "
    "RESULTSET_SIZE 10000"
)


def wait_ping(port: int, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = redis.Redis(port=port, socket_connect_timeout=1)
            if r.ping():
                r.execute_command("GRAPH.LIST")  # the graph module answers too
                return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError("FalkorDB did not come back")


class Server:
    def __init__(self, port: int, restart: Callable[[], None]) -> None:
        self.port = port
        self.url = f"redis://127.0.0.1:{port}"
        self.restart = restart


@pytest.fixture(scope="module")
def server() -> Iterator[Server]:
    name = f"actron-scratch-{uuid.uuid4().hex[:8]}"
    with socket.socket() as sock:  # fixed host port: docker picks a new random one on restart
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    volume = f"{name}-data"
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-p",
                f"127.0.0.1:{port}:6379",
                "-v",
                f"{volume}:/var/lib/falkordb/data",
                "-e",
                "REDIS_ARGS=--appendonly yes",
                "-e",
                f"FALKORDB_ARGS={FALKORDB_ARGS}",
                "-e",
                "BROWSER=0",
                IMAGE,
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"cannot start a FalkorDB container: {exc}")
    try:
        wait_ping(port)

        def restart() -> None:
            subprocess.run(
                ["docker", "restart", name], check=True, capture_output=True, timeout=120
            )
            wait_ping(port)

        yield Server(port, restart)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", "-f", volume], capture_output=True)
