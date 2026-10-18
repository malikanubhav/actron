"""A-AC-71: reference patterns behave as specified on a table of true and false positives for every kind."""

from __future__ import annotations

import pytest

from actron.linking.references import RefContext, branch_keys, find_references

REPO = "betterthantomorrow/calva"
TEAMS = frozenset({"CAL", "ENG"})
WITH_TEAMS = RefContext(repo=REPO, team_keys=TEAMS)
NO_TEAMS = RefContext(repo=REPO)
NO_REPO = RefContext(team_keys=TEAMS)

# (case id, text, context, expected [(stored kind, key)])
CASES: list[tuple[str, str, RefContext, list[tuple[str, str]]]] = [
    # linear_issue (known team keys)
    ("lin-1", "Fixed in CAL-12 today", WITH_TEAMS, [("linear_issue", "CAL-12")]),
    (
        "lin-2",
        "See ENG-7 and CAL-40.",
        WITH_TEAMS,
        [("linear_issue", "ENG-7"), ("linear_issue", "CAL-40")],
    ),
    ("lin-3", "(CAL-3)", WITH_TEAMS, [("linear_issue", "CAL-3")]),
    ("lin-4", "OPS-12 is another team", WITH_TEAMS, []),
    ("lin-5", "cal-12 lower case is not a key", WITH_TEAMS, []),
    ("lin-6", "CAL-0012 normalises", WITH_TEAMS, [("linear_issue", "CAL-12")]),
    ("lin-7", "XCAL-12 longer prefix", WITH_TEAMS, []),
    ("lin-8", "CAL-1234567 too many digits", WITH_TEAMS, []),
    # linear_issue with no team known yet: stored pending, but standards are excluded
    ("lin-9", "Tracked as OPS-9", NO_TEAMS, [("linear_issue", "OPS-9")]),
    ("lin-fp-1", "Server answered HTTP-200", NO_TEAMS, []),
    ("lin-fp-2", "Files are UTF-8 encoded", NO_TEAMS, []),
    ("lin-fp-3", "Dates use ISO-8601", NO_TEAMS, []),
    ("lin-fp-4", "Hash with SHA-256 please", NO_TEAMS, []),
    ("lin-fp-5", "HTTP-200 UTF-8 ISO-8601 SHA-256", WITH_TEAMS, []),
    ("lin-fp-6", "Patched for CVE-2024 issues", NO_TEAMS, []),
    # linear_url
    (
        "lurl-1",
        "https://linear.app/calva/issue/CAL-12/fix-paste",
        WITH_TEAMS,
        [("linear_issue", "CAL-12")],
    ),
    (
        "lurl-2",
        "Ticket: https://linear.app/acme/issue/OPS-3",
        WITH_TEAMS,
        [("linear_issue", "OPS-3")],
    ),
    ("lurl-3", "https://linear.app/acme/project/roadmap-1", WITH_TEAMS, []),
    # github_pr_or_issue
    ("gh-1", "Closes #123", NO_REPO, []),
    ("gh-2", "Closes #123", WITH_TEAMS, [("github_pr", f"{REPO}#123")]),
    ("gh-3", "see BetterThanTomorrow/calva#2401", NO_REPO, [("github_pr", f"{REPO}#2401")]),
    (
        "gh-4",
        "upstream clojure-lsp/clojure-lsp#88 too",
        WITH_TEAMS,
        [("github_pr", "clojure-lsp/clojure-lsp#88")],
    ),
    ("gh-5", "issue#12 is glued", WITH_TEAMS, []),
    ("gh-6", "(#45)", WITH_TEAMS, [("github_pr", f"{REPO}#45")]),
    ("gh-fp-1", "colour #fff and #a0b0c0", WITH_TEAMS, []),
    ("gh-fp-2", "```python\n# step #1: load\nx = 1\n```", WITH_TEAMS, []),
    ("gh-fp-3", "HTML entity &#123; is not an issue", WITH_TEAMS, []),
    ("gh-fp-4", "inline `#7` is code", WITH_TEAMS, []),
    ("gh-fp-5", "## Heading", WITH_TEAMS, []),
    # github_url
    (
        "ghu-1",
        "https://github.com/BetterThanTomorrow/calva/pull/2500",
        NO_REPO,
        [("github_pr", f"{REPO}#2500")],
    ),
    (
        "ghu-2",
        "https://github.com/BetterThanTomorrow/calva/issues/77#issuecomment-1",
        NO_REPO,
        [("github_issue", f"{REPO}#77")],
    ),
    (
        "ghu-3",
        "https://github.com/BetterThanTomorrow/calva/pull/12/files",
        WITH_TEAMS,
        [("github_pr", f"{REPO}#12")],
    ),
    (
        "ghu-4",
        "https://github.com/BetterThanTomorrow/calva/blob/dev/src/extension.ts",
        WITH_TEAMS,
        [],
    ),
    ("ghu-5", "https://github.com/BetterThanTomorrow/calva/tree/dev", WITH_TEAMS, []),
    # commit
    ("c-1", "Fixed in commit 1a2b3c4d", WITH_TEAMS, [("commit", "1a2b3c4d")]),
    (
        "c-2",
        "commit: 0123abcdef0123abcdef0123abcdef0123abcdef",
        WITH_TEAMS,
        [("commit", "0123abcdef0123abcdef0123abcdef0123abcdef")],
    ),
    ("c-3", "reverted `9f8e7d6` yesterday", WITH_TEAMS, [("commit", "9f8e7d6")]),
    (
        "c-4",
        "https://github.com/BetterThanTomorrow/calva/commit/abc1234def",
        WITH_TEAMS,
        [("commit", "abc1234def")],
    ),
    ("c-5", "commits 7777aaa landed", WITH_TEAMS, [("commit", "7777aaa")]),
    ("c-fp-1", "build 1a2b3c4d failed", WITH_TEAMS, []),
    ("c-fp-2", "released v1.2.3 and v2.10.0", WITH_TEAMS, []),
    ("c-fp-3", "commit abc12 too short", WITH_TEAMS, []),
    ("c-fp-4", "the number 12345678 alone", WITH_TEAMS, []),
    # upper-case hex is never a commit; it stays a symbol candidate that resolves only against code
    ("c-fp-5", "`ABCDEF12` upper case", WITH_TEAMS, [("symbol", "ABCDEF12")]),
    # file (candidates; resolution needs a unique CodeFile match)
    ("f-1", "Look at src/extension.ts first", WITH_TEAMS, [("file", "src/extension.ts")]),
    (
        "f-2",
        "the bug is in `src/cursor-doc/paredit.ts`",
        WITH_TEAMS,
        [("file", "src/cursor-doc/paredit.ts")],
    ),
    (
        "f-3",
        "edit ./src/calva-fmt/src/format.ts",
        WITH_TEAMS,
        [("file", "src/calva-fmt/src/format.ts")],
    ),
    (
        "f-4",
        "src/nrepl/repl-session.ts:120 throws",
        WITH_TEAMS,
        [("file", "src/nrepl/repl-session.ts")],
    ),
    ("f-fp-1", "use and/or here", WITH_TEAMS, []),
    ("f-fp-2", "dates 10/17/2026", WITH_TEAMS, []),
    ("f-fp-3", "https://calva.io/docs/paredit.md", WITH_TEAMS, []),
    ("f-fp-4", "ratio 3/4 done", WITH_TEAMS, []),
    # symbol (candidates; resolution needs a CodeFunction or CodeClass)
    ("s-1", "call `activate` on start", WITH_TEAMS, [("symbol", "activate")]),
    ("s-2", "`NReplSession.eval` hangs", WITH_TEAMS, [("symbol", "NReplSession.eval")]),
    ("s-3", "formatCode() is slow", WITH_TEAMS, [("symbol", "formatCode")]),
    ("s-4", "`paredit-forward` in Clojure", WITH_TEAMS, [("symbol", "paredit-forward")]),
    ("s-5", "`calva.fmt/format-code` ns fn", WITH_TEAMS, [("symbol", "calva.fmt/format-code")]),
    ("s-fp-1", "`true` and `null`", WITH_TEAMS, []),
    ("s-fp-2", "`npm` runs it", WITH_TEAMS, []),
    ("s-fp-3", "`go` is short", WITH_TEAMS, []),
    ("s-fp-4", "a function call () alone", WITH_TEAMS, []),
    # slack_permalink
    (
        "sl-1",
        "https://calva.slack.com/archives/C0456ABC/p1712345678000100",
        WITH_TEAMS,
        [("slack_message", "C0456ABC:1712345678.000100")],
    ),
    (
        "sl-2",
        "thread https://clojurians.slack.com/archives/CBE668G4R/p1700000000123456?thread_ts=1",
        WITH_TEAMS,
        [("slack_message", "CBE668G4R:1700000000.123456")],
    ),
    ("sl-fp-1", "https://calva.slack.com/archives/C0456ABC", WITH_TEAMS, []),
    ("sl-fp-2", "https://calva.slack.com/archives/D0456ABC/p1712345678000100", WITH_TEAMS, []),
    # mixed text
    (
        "mix-1",
        "CAL-12: fixes #34 via `src/extension.ts`, see commit deadbee1",
        WITH_TEAMS,
        [
            ("linear_issue", "CAL-12"),
            ("github_pr", f"{REPO}#34"),
            ("file", "src/extension.ts"),
            ("commit", "deadbee1"),
        ],
    ),
    (
        "mix-2",
        "https://github.com/BetterThanTomorrow/calva/pull/9 for CAL-9",
        WITH_TEAMS,
        [("github_pr", f"{REPO}#9"), ("linear_issue", "CAL-9")],
    ),
]


@pytest.mark.parametrize(("case", "text", "ctx", "expected"), CASES, ids=[c[0] for c in CASES])
def test_reference_table(
    case: str, text: str, ctx: RefContext, expected: list[tuple[str, str]]
) -> None:
    """A-AC-71."""
    got = [(r.kind, r.key) for r in find_references(text, ctx)]
    assert got == expected


def test_table_size() -> None:
    """A-AC-71: at least 60 cases, with false positives for every kind."""
    assert len(CASES) >= 60
    for prefix in ("lin-fp", "gh-fp", "c-fp", "f-fp", "s-fp", "sl-fp"):
        assert any(c[0].startswith(prefix) for c in CASES)


def test_quote_span_points_at_match() -> None:
    """A-AC-71: spans point at the matched text."""
    text = "Fixed in CAL-12 today"
    [ref] = find_references(text, WITH_TEAMS)
    assert (
        text[ref.start : ref.end] == "CAL-12"
        and ref.raw == "CAL-12"
        and ref.pattern == "linear_issue"
    )


@pytest.mark.parametrize(
    ("ref", "keys", "expected"),
    [
        ("cal-12-fix-paste", TEAMS, ["CAL-12"]),
        ("feature/ENG-7-new-setting", TEAMS, ["ENG-7"]),
        ("feature-12", TEAMS, []),
        ("cal-12-fix", frozenset(), []),
        ("dev", TEAMS, []),
    ],
)
def test_branch_keys(ref: str, keys: frozenset[str], expected: list[str]) -> None:
    """A-AC-71 branch kind / A-AC-73: Linear keys inside a PR branch name."""
    assert branch_keys(ref, keys) == expected
