"""In-memory results of parsing one file, shared by every parser and later steps (spec A, A6)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

SymbolKind = Literal["function", "class"]
FunctionKind = Literal["function", "method", "constructor", "property", "nested"]
CallKind = Literal["call", "new", "macro"]


@dataclass
class CallSite:
    """One call inside a function body. `callee` is the callee expression text (`foo`, `self.bar`, `mod.baz`)."""

    callee: str
    line: int
    kind: CallKind = "call"


@dataclass
class Symbol:
    """A function or class with exact 1-based inclusive line ranges."""

    kind: SymbolKind
    name: str
    qualname: str
    start_line: int
    end_line: int
    body: str
    dup: int = 1
    fn_kind: FunctionKind | None = None
    docstring: str | None = None
    signature: str | None = None
    parameters: list[str] = field(default_factory=list)
    return_type: str | None = None
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    is_async: bool = False
    is_public: bool = True
    is_test: bool = False
    # Qualified name (with dup suffix) of the enclosing class or function, if any.
    parent: str | None = None
    parent_kind: SymbolKind | None = None
    calls: list[CallSite] = field(default_factory=list)
    parent_obj: Symbol | None = field(default=None, repr=False, compare=False)

    @property
    def key(self) -> str:
        """Qualified name with the `~n` suffix, unique inside the file."""
        return self.qualname if self.dup == 1 else f"{self.qualname}~{self.dup}"

    @property
    def loc(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def content_hash(self) -> str:
        return sha256_text(self.body)


@dataclass
class ImportRec:
    """One import statement. `module` is the specifier as written (`a.b`, `./x`, `calva.bar`)."""

    module: str
    line: int
    names: list[tuple[str, str]] = field(default_factory=list)  # (imported name, local alias)
    alias: str | None = None  # `import a.b as c`, `import * as ns`, Clojure `:as`
    star: bool = False
    level: int = 0  # Python relative import dots
    dynamic: bool = False  # `import()` and `require()`: low confidence


@dataclass
class ParsedFile:
    path: str
    language: str
    tier: int
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRec] = field(default_factory=list)
    exports: list[str] | None = None  # Python `__all__`
    module_calls: list[CallSite] = field(default_factory=list)  # calls outside any function
    namespace: str | None = None  # Go package, Java package, Clojure ns
    default_export: str | None = None  # TS/JS: local name of `export default`
    parse_error: bool = False

    def functions(self) -> list[Symbol]:
        return [s for s in self.symbols if s.kind == "function"]

    def classes(self) -> list[Symbol]:
        return [s for s in self.symbols if s.kind == "class"]

    def top_level(self) -> list[Symbol]:
        return [s for s in self.symbols if s.parent is None]

    def by_key(self) -> dict[str, Symbol]:
        return {s.key: s for s in self.symbols}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_lines(text: str) -> list[str]:
    """Lines as git and tree-sitter count them: split on `\\n` only; a trailing newline adds no line."""
    if not text:
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def finalize(symbols: list[Symbol]) -> list[Symbol]:
    """Sort by position, give repeated qualified names `~2`, `~3` in source order, fill parent keys."""
    symbols.sort(key=lambda s: (s.start_line, -s.end_line))
    seen: dict[str, int] = {}
    for sym in symbols:
        n = seen.get(sym.qualname, 0) + 1
        seen[sym.qualname] = n
        sym.dup = n
    for sym in symbols:
        if sym.parent_obj is not None:
            sym.parent = sym.parent_obj.key
            sym.parent_kind = sym.parent_obj.kind
    return symbols
