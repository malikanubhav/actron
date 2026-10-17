"""Public boundaries shared by ingestion, workflow and execution.

Payloads are JSON-compatible so immutable evidence and operation records can be
inspected without importing application classes. Provider methods must confirm
writes or raise UnknownOutcome; absence must be established before retrying.
"""

import hashlib
import json
from contextlib import AbstractContextManager
from typing import Any, Protocol

Payload = dict[str, Any]


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Unavailable(RuntimeError):
    """A dependency failed; do not substitute unsupported evidence."""


class UnknownOutcome(Unavailable):
    """An external operation may have completed; reconcile before retry."""


class Rejected(RuntimeError):
    """An invariant or authorization gate prevented an operation."""


class Store(Protocol):
    def get(self, kind: str, key: str) -> Payload | None: ...
    def put(self, kind: str, key: str, value: Payload) -> None: ...
    def list(self, kind: str) -> list[Payload]: ...
    def link(
        self,
        left_kind: str,
        left: str,
        relation: str,
        right_kind: str,
        right: str,
        provenance: Payload,
    ) -> None: ...
    def lock(self, key: str) -> AbstractContextManager[None]: ...


class Slack(Protocol):
    def post(
        self,
        channel: str,
        text: str,
        thread: str | None = None,
        blocks: list[Payload] | None = None,
    ) -> str: ...


class Tickets(Protocol):
    def create(self, operation: str, scope: Payload) -> Payload: ...
    def find(self, operation: str) -> Payload | None: ...
    def read(self, issue: str) -> Payload: ...
    def update(self, issue: str, scope: Payload) -> Payload: ...


class PullRequests(Protocol):
    def create(self, operation: str, run: Payload, scope: Payload) -> Payload: ...
    def find(self, operation: str) -> Payload | None: ...
    def read(self, pr: str) -> Payload: ...
    def merge(self, pr: str, expected_head: str) -> Payload: ...


class Worker(Protocol):
    def run(
        self, operation: str, scope: Payload, evidence: Payload, base: str, feedback: str = ""
    ) -> Payload: ...
    def find(self, operation: str) -> Payload | None: ...


class Sources(Protocol):
    def fetch(self, cursor: str | None = None) -> Payload: ...
