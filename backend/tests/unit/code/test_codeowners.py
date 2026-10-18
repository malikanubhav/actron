"""A-AC-34: CODEOWNERS with overlapping patterns; the last matching rule wins (gitignore semantics)."""

from __future__ import annotations

from actron.connectors.code.codeowners import match_owner, parse_codeowners

FIXTURE = """\
# default owners
*                @org/everyone
*.ts             @ts-team
/docs/           @docs-team
src/**/test/     @qa
/src/extension.ts @alice bob@example.com
build/           @build
**/fixtures/*.json @fixtures   # inline comment
"""


def test_last_matching_rule_wins() -> None:
    """A-AC-34"""
    rules = parse_codeowners(FIXTURE)
    assert [r.line for r in rules] == [2, 3, 4, 5, 6, 7, 8]

    def owner(path: str) -> list[str]:
        rule = match_owner(path, rules)
        assert rule is not None
        return rule.owners

    assert owner("README.md") == ["@org/everyone"]
    assert owner("src/util.ts") == ["@ts-team"]
    assert owner("docs/guide.ts") == ["@docs-team"]  # later /docs/ beats *.ts
    assert owner("nested/docs/x.md") == ["@org/everyone"]  # /docs/ is anchored at the root
    assert owner("src/a/b/test/x.ts") == ["@qa"]
    assert owner("src/extension.ts") == ["@alice", "bob@example.com"]
    assert owner("lib/src/extension.ts") == ["@ts-team"]
    assert owner("tools/build/out.js") == ["@build"]  # unanchored directory pattern
    assert owner("a/fixtures/x.json") == ["@fixtures"]
    assert owner("a/fixtures/deep/x.json") == ["@org/everyone"]


def test_no_rules_no_owner() -> None:
    """A-AC-34"""
    assert match_owner("a.py", parse_codeowners("# only comments\n")) is None
