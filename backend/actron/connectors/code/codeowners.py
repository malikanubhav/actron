"""CODEOWNERS rules with gitignore-style patterns; the last matching rule wins (spec A, A6.8)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


@dataclass
class OwnerRule:
    line: int
    pattern: str
    owners: list[str]
    regex: re.Pattern[str] = field(repr=False, compare=False, default=re.compile(""))


def pattern_regex(pattern: str) -> re.Pattern[str]:
    pat = pattern
    directory = pat.endswith("/")
    pat = pat.rstrip("/")
    anchored = pat.startswith("/") or "/" in pat
    pat = pat.lstrip("/")
    out: list[str] = []
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out.append("/.*")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        elif pat[i] == "\\" and i + 1 < len(pat):
            out.append(re.escape(pat[i + 1]))
            i += 2
        else:
            out.append(re.escape(pat[i]))
            i += 1
    body = "".join(out)
    prefix = "^" if anchored else "^(?:.*/)?"
    suffix = "/.*$" if directory else "(?:/.*)?$"
    return re.compile(prefix + body + suffix)


def parse_codeowners(text: str) -> list[OwnerRule]:
    rules: list[OwnerRule] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"\s+#.*$", "", line)
        parts = re.split(r"(?<!\\)\s+", line)
        pattern, owners = parts[0], parts[1:]
        rules.append(OwnerRule(n, pattern, owners, pattern_regex(pattern)))
    return rules


def match_owner(path: str, rules: list[OwnerRule]) -> OwnerRule | None:
    hit: OwnerRule | None = None
    for rule in rules:
        if rule.regex.match(path):
            hit = rule
    return hit
