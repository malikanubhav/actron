"""Structured JSON logs with request and workflow ids; secrets are redacted (spec A, A-AC-4)."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
workflow_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "workflow_id", default=None
)

_REDACTED = "[REDACTED]"
# Token shapes that must never reach a log line even when they are not in settings.
_TOKEN_PATTERNS = [
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"xapp-[A-Za-z0-9-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"lin_api_[A-Za-z0-9]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(bearer\s+)?[A-Za-z0-9._~+/-]{12,}"),
]
_SECRET_KEYS = re.compile(r"(?i)(key|token|secret|password|authorization)$")


class Redactor:
    def __init__(self) -> None:
        self._values: set[str] = set()

    def add(self, values: Iterable[str]) -> None:
        for v in values:
            if v and len(v) >= 6:
                self._values.add(v)

    def scrub(self, text: str) -> str:
        for v in sorted(self._values, key=len, reverse=True):
            if v in text:
                text = text.replace(v, _REDACTED)
        for pat in _TOKEN_PATTERNS:
            if pat.groups >= 1:
                text = pat.sub(lambda m: (m.group(1) or "") + _REDACTED, text)
            else:
                text = pat.sub(_REDACTED, text)
        return text

    def scrub_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.scrub(obj)
        if isinstance(obj, dict):
            return {
                k: (
                    _REDACTED
                    if isinstance(k, str) and _SECRET_KEYS.search(k) and v
                    else self.scrub_obj(v)
                )
                for k, v in obj.items()
            }
        if isinstance(obj, list | tuple):
            return [self.scrub_obj(v) for v in obj]
        return obj


redactor = Redactor()

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        wid = workflow_id_var.get()
        if rid:
            payload["request_id"] = rid
        if wid:
            payload["workflow_id"] = wid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        payload = redactor.scrub_obj(payload)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    redactor.add(secrets)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "LiteLLM", "litellm", "urllib3", "temporalio.activity"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
