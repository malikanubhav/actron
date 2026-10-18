"""A-AC-4: logs are JSON lines with level, msg, ts and ids; secrets never appear (capturing handler)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest

from actron import logging as alog
from actron.config import Settings, load_settings


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(alog.JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def cap() -> Iterator[tuple[logging.Logger, Capture]]:
    handler = Capture()
    logger = logging.getLogger("actron.test.redaction")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    saved = set(alog.redactor._values)
    alog.redactor._values.clear()
    yield logger, handler
    alog.redactor._values.clear()
    alog.redactor._values.update(saved)
    logger.handlers[:] = []


def test_line_is_json_with_required_fields_a_ac_4(cap: tuple[logging.Logger, Capture]) -> None:
    """A-AC-4"""
    logger, handler = cap
    logger.info("hello %s", "world")
    data = json.loads(handler.lines[0])
    assert data["level"] == "info"
    assert data["msg"] == "hello world"
    assert data["ts"].endswith("Z")
    assert "request_id" not in data


def test_request_and_workflow_ids_are_added_a_ac_4(cap: tuple[logging.Logger, Capture]) -> None:
    """A-AC-4"""
    logger, handler = cap
    t1 = alog.request_id_var.set("req_01ABC")
    t2 = alog.workflow_id_var.set("wf-1")
    try:
        logger.warning("working")
    finally:
        alog.request_id_var.reset(t1)
        alog.workflow_id_var.reset(t2)
    data = json.loads(handler.lines[0])
    assert data["request_id"] == "req_01ABC"
    assert data["workflow_id"] == "wf-1"
    assert data["level"] == "warning"


def test_extra_fields_are_kept(cap: tuple[logging.Logger, Capture]) -> None:
    logger, handler = cap
    logger.info("batch", extra={"count": 3})
    assert json.loads(handler.lines[0])["count"] == 3


@pytest.mark.parametrize(
    "name", [n for n in Settings.model_fields if n.endswith(("KEY", "TOKEN", "SECRET"))]
)
def test_every_configured_secret_is_redacted_a_ac_4(
    name: str, cap: tuple[logging.Logger, Capture]
) -> None:
    """A-AC-4: any setting ending in KEY, TOKEN or SECRET never appears in a log line."""
    logger, handler = cap
    value = f"s3cr3t-{name.lower()}-value-9f8e7d"
    kwargs: dict[str, object] = {name: value}
    if name == "ACTRON_SECRET_KEY":
        from cryptography.fernet import Fernet

        value = Fernet.generate_key().decode()
        kwargs = {name: value}
    settings = load_settings(_env_file=None, **kwargs)
    alog.redactor.add(settings.secret_values())
    logger.info("calling with %s", value)
    logger.info("plain message", extra={"detail": f"url=https://x/?k={value}"})
    try:
        raise RuntimeError(f"failed using {value}")
    except RuntimeError:
        logger.exception("boom")
    for line in handler.lines:
        assert value not in line
    assert "[REDACTED]" in handler.lines[0]


def test_connector_secret_added_at_runtime_is_redacted_a_ac_4(
    cap: tuple[logging.Logger, Capture],
) -> None:
    """A-AC-4: connector secrets (stored per workspace, not in settings) are redacted once registered."""
    logger, handler = cap
    alog.redactor.add(["connector-secret-abcdef123456"])
    logger.info(
        "token is connector-secret-abcdef123456",
        extra={"payload": {"a": ["connector-secret-abcdef123456"]}},
    )
    assert "connector-secret-abcdef123456" not in handler.lines[0]


@pytest.mark.parametrize(
    "token",
    [
        "xoxb-1234567890-abcdefghij",
        "xapp-1-A0123456789-abcdef",
        "ghp_" + "a" * 36,
        "github_pat_" + "B" * 30,
        "lin_api_" + "c" * 30,
        "sk-ant-api03-" + "d" * 30,
    ],
)
def test_token_shapes_are_redacted_even_when_unknown_a_ac_4(
    token: str, cap: tuple[logging.Logger, Capture]
) -> None:
    """A-AC-4"""
    logger, handler = cap
    logger.info("got %s from api", token)
    assert token not in handler.lines[0]


def test_authorization_header_and_secret_keys_are_redacted_a_ac_4(
    cap: tuple[logging.Logger, Capture],
) -> None:
    """A-AC-4"""
    logger, handler = cap
    logger.info(
        "request",
        extra={
            "headers": {"Authorization": "Bearer abcdefghijklmnop12345", "api_key": "plainvalue1"}
        },
    )
    line = handler.lines[0]
    assert "abcdefghijklmnop12345" not in line
    assert "plainvalue1" not in line


def test_short_values_are_not_registered() -> None:
    r = alog.Redactor()
    r.add(["abc", ""])
    assert r.scrub("abc stays") == "abc stays"


def test_configure_logging_replaces_handlers_and_registers_secrets() -> None:
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    saved_values = set(alog.redactor._values)
    try:
        alog.configure_logging("DEBUG", secrets=["registered-secret-123456"])
        assert len(root.handlers) == 1
        assert "registered-secret-123456" in alog.redactor._values
    finally:
        root.handlers[:] = saved
        root.setLevel(saved_level)
        alog.redactor._values.clear()
        alog.redactor._values.update(saved_values)
