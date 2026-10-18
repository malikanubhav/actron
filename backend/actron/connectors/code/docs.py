"""Markdown and reStructuredText sections and their explicit mentions of code (spec A, A6.8).

Sections partition the file: each runs from its heading to the line before the next heading. Lines before
the first heading form a preamble section titled with the file name (level 0), so every line is covered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from actron.connectors.code.model import split_lines
from actron.graph.ids import slugify

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SETEXT1 = re.compile(r"^ {0,3}=+[ \t]*$")
_SETEXT2 = re.compile(r"^ {0,3}-+[ \t]*$")
_RST_ADORN = re.compile(r"^([=\-~^\"'`#*+:._!$%&,;<>?@\\|/(){}\[\]])\1{2,}\s*$")
_CODE_SPAN = re.compile(r"(`+)([^`\n]+?)\1")
_FILE_LIKE = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_IDENT = re.compile(r"^[A-Za-z_$][\w$.:!?*<>=-]*$")


@dataclass
class Section:
    title: str
    level: int
    start: int
    end: int
    text: str
    slug: str
    dup: int = 1
    parent: int | None = None  # index of the parent section in the list

    @property
    def key(self) -> str:
        return self.slug if self.dup == 1 else f"{self.slug}~{self.dup}"


@dataclass
class _Heading:
    line: int
    level: int
    title: str


def _markdown_headings(lines: list[str]) -> list[_Heading]:
    out: list[_Heading] = []
    fence: str | None = None
    i = 0
    if lines and lines[0].strip() == "---":  # YAML front matter stays in the preamble
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                i = j + 1
                break
    while i < len(lines):
        line = lines[i]
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            i += 1
            continue
        if m:
            fence = m.group(1)
            i += 1
            continue
        a = _ATX.match(line)
        if a:
            out.append(_Heading(i + 1, len(a.group(1)), (a.group(2) or "").strip()))
            i += 1
            continue
        paragraph = line.strip() and not line.startswith(("    ", "\t", ">", "- ", "* ", "+ ", "|"))
        if paragraph and i + 1 < len(lines):
            nxt = lines[i + 1]
            if _SETEXT1.match(nxt) or _SETEXT2.match(nxt):
                out.append(_Heading(i + 1, 1 if _SETEXT1.match(nxt) else 2, line.strip()))
                i += 2
                continue
        i += 1
    return out


def _rst_headings(lines: list[str]) -> list[_Heading]:
    """Headings start at their overline when there is one, else at the title line."""
    out: list[_Heading] = []
    styles: list[tuple[str, bool]] = []
    i = 0
    while i < len(lines) - 1:
        line = lines[i]
        if (_RST_ADORN.match(line) and i + 2 < len(lines) and _RST_ADORN.match(lines[i + 2])
                and lines[i + 1].strip() and line.strip()[0] == lines[i + 2].strip()[0]):
            style = (line.strip()[0], True)
            if style not in styles:
                styles.append(style)
            out.append(_Heading(i + 1, styles.index(style) + 1, lines[i + 1].strip()))
            i += 3
            continue
        nxt = lines[i + 1]
        if (line.strip() and not _RST_ADORN.match(line) and _RST_ADORN.match(nxt)
                and len(nxt.rstrip()) >= len(line.rstrip()) and not line.startswith((" ", "\t"))):
            style = (nxt.strip()[0], False)
            if style not in styles:
                styles.append(style)
            out.append(_Heading(i + 1, styles.index(style) + 1, line.strip()))
            i += 2
            continue
        i += 1
    return out


def split_document(path: str, text: str) -> list[Section]:
    lines = split_lines(text)
    if not lines:
        return []
    is_rst = PurePosixPath(path).suffix.lower() == ".rst"
    headings = _rst_headings(lines) if is_rst else _markdown_headings(lines)
    sections: list[Section] = []
    starts = [h.line for h in headings]
    if not starts or starts[0] > 1:
        end = (starts[0] - 1) if starts else len(lines)
        name = PurePosixPath(path).name
        sections.append(Section(name, 0, 1, end, "\n".join(lines[:end]), slugify(name)))
    for idx, h in enumerate(headings):
        end = headings[idx + 1].line - 1 if idx + 1 < len(headings) else len(lines)
        sections.append(Section(h.title or "section", h.level, h.line, end, "\n".join(lines[h.line - 1 : end]),
                                slugify(h.title)))
    sections = [s for s in sections if s.end >= s.start]
    # dup suffixes in source order, and parents by heading level
    seen: dict[str, int] = {}
    stack: list[int] = []
    for i, s in enumerate(sections):
        seen[s.slug] = seen.get(s.slug, 0) + 1
        s.dup = seen[s.slug]
        if s.level == 0:
            continue
        while stack and sections[stack[-1]].level >= s.level:
            stack.pop()
        s.parent = stack[-1] if stack else None
        stack.append(i)
    return sections


@dataclass
class MentionIndex:
    """Snapshot lookup for explicit mentions: paths, qualified names and plain names to node ids."""

    files: dict[str, str] = field(default_factory=dict)  # path -> file id
    qualnames: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # qualname -> [(label, id)]
    names: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # name -> [(label, id)]

    def add_symbol(self, label: str, node_id: str, name: str, qualname: str) -> None:
        self.qualnames.setdefault(qualname, []).append((label, node_id))
        self.names.setdefault(name, []).append((label, node_id))

    def resolve_path(self, token: str) -> str | None:
        token = token.removeprefix("./").lstrip("/")
        if token in self.files:
            return self.files[token]
        matches = [fid for p, fid in self.files.items() if p.endswith("/" + token)]
        return matches[0] if len(matches) == 1 else None

    def resolve_symbol(self, token: str) -> tuple[str, str] | None:
        for table in (self.qualnames, self.names):
            hits = table.get(token)
            if hits:
                return hits[0] if len({h[1] for h in hits}) == 1 else None
        return None


def find_mentions(text: str, index: MentionIndex) -> list[tuple[str, str]]:
    """Backticked identifiers and paths that resolve uniquely → [(label, id)] (deduplicated, in order)."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    in_fence = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _CODE_SPAN.finditer(line):
            token = m.group(2).strip()
            if not token or " " in token.strip("()") or len(token) > 200:
                continue
            token = token.removesuffix("()").strip(",;:")
            hit: tuple[str, str] | None = None
            if "/" in token:
                fid = index.resolve_path(token)
                hit = ("CodeFile", fid) if fid else None
            else:
                if _FILE_LIKE.search(token):
                    fid = index.resolve_path(token)
                    hit = ("CodeFile", fid) if fid else None
                if hit is None and _IDENT.match(token):
                    hit = index.resolve_symbol(token)
            if hit is not None and hit[1] not in seen:
                seen.add(hit[1])
                out.append(hit)
    return out
