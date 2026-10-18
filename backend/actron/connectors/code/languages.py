"""File extension to language, grammar and tier (spec A, A6.2)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class Lang:
    name: str  # language stored on CodeFile.language
    grammar: str | None  # tree-sitter-language-pack grammar name, None when not parsed
    tier: int  # 1 full rules, 2 generic rules, 0 documents, -1 plain text


_EXT: dict[str, Lang] = {}


def _add(exts: str, lang: Lang) -> None:
    for ext in exts.split():
        _EXT[ext] = lang


_add(".py .pyi", Lang("python", "python", 1))
_add(".ts .mts .cts", Lang("typescript", "typescript", 1))
_add(".tsx", Lang("tsx", "tsx", 1))
_add(".js .mjs .cjs .jsx", Lang("javascript", "javascript", 1))
_add(".go", Lang("go", "go", 1))
_add(".java", Lang("java", "java", 1))
_add(".rs", Lang("rust", "rust", 1))
_add(".kt .kts", Lang("kotlin", "kotlin", 2))
_add(".rb", Lang("ruby", "ruby", 2))
_add(".php", Lang("php", "php", 2))
_add(".c .h", Lang("c", "c", 2))
_add(".cc .cpp .cxx .hpp", Lang("cpp", "cpp", 2))
_add(".scala", Lang("scala", "scala", 2))
_add(".swift", Lang("swift", "swift", 2))
_add(".clj .cljs .cljc .edn", Lang("clojure", "clojure", 2))
_add(".md .mdx .markdown", Lang("markdown", None, 0))
_add(".rst", Lang("rst", None, 0))

CONFIG_EXTS = frozenset([".toml", ".json", ".jsonc", ".yaml", ".yml", ".cfg", ".ini", ".conf", ".properties", ".env", ".editorconfig"])
DATA_EXTS = frozenset([".csv", ".tsv", ".psv", ".ndjson", ".jsonl"])
TEXT_TYPES: dict[str, str] = {
    ".toml": "toml", ".json": "json", ".jsonc": "json", ".yaml": "yaml", ".yml": "yaml", ".cfg": "ini",
    ".ini": "ini", ".txt": "text", ".sql": "sql", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss", ".less": "less", ".xml": "xml",
    ".svg": "svg", ".csv": "csv", ".tsv": "tsv", ".bb": "clojure-script", ".lpy": "basilisp",
}


def ext_of(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def language_for(path: str) -> Lang:
    ext = ext_of(path)
    lang = _EXT.get(ext)
    if lang is not None:
        return lang
    name = PurePosixPath(path).name
    if name in ("Dockerfile", "Makefile", "CODEOWNERS"):
        return Lang(name.lower(), None, -1)
    return Lang(TEXT_TYPES.get(ext, ext.lstrip(".") or "text"), None, -1)


def chunk_kind(path: str, has_code: bool) -> str:
    ext = ext_of(path)
    if ext in CONFIG_EXTS:
        return "config"
    if ext in DATA_EXTS:
        return "data"
    if has_code or language_for(path).tier in (1, 2):
        return "module_level"
    return "other"


@cache
def parser_for(grammar: str) -> Any:
    from tree_sitter_language_pack import get_parser

    return get_parser(grammar)
