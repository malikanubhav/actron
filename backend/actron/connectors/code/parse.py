"""Pick the parser for a file by language (spec A, A6.2)."""

from __future__ import annotations

from actron.connectors.code.languages import language_for
from actron.connectors.code.model import ParsedFile
from actron.connectors.code.parse_generic import parse_generic
from actron.connectors.code.parse_go import parse_go
from actron.connectors.code.parse_java import parse_java
from actron.connectors.code.parse_python import parse_python
from actron.connectors.code.parse_rust import parse_rust
from actron.connectors.code.parse_typescript import parse_typescript


def parse_file(path: str, source: bytes) -> ParsedFile | None:
    """Parse a code file; returns None for documents and plain text."""
    lang = language_for(path)
    if lang.tier not in (1, 2) or lang.grammar is None:
        return None
    name = lang.name
    if name == "python":
        return parse_python(path, source)
    if name in ("typescript", "tsx", "javascript"):
        return parse_typescript(path, source, name)
    if name == "go":
        return parse_go(path, source)
    if name == "java":
        return parse_java(path, source)
    if name == "rust":
        return parse_rust(path, source)
    return parse_generic(path, source, name)
