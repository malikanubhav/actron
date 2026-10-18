"""Slack text normalisation (A-AC-54): user, channel and link markup, table driven."""

from __future__ import annotations

import pytest

from actron.connectors.slack import normalize_slack_text

USERS = {"U1": "Ada Lovelace", "W9": "Grace"}
CHANNELS = {"C1": "general", "C2": "eng-backend"}

CASES = [
    ("user mention with known name", "hi <@U1>", "hi @Ada Lovelace"),
    ("user mention unknown id", "ping <@U404>", "ping @U404"),
    ("user mention with label wins", "thanks <@U1|ada>!", "thanks @ada!"),
    ("enterprise user id", "<@W9> approved", "@Grace approved"),
    ("channel with label", "see <#C1|general>", "see #general"),
    ("channel without label uses map", "see <#C2>", "see #eng-backend"),
    ("channel unknown", "see <#C9>", "see #C9"),
    ("link with label", "docs: <https://example.com/a|the docs>", "docs: the docs (https://example.com/a)"),
    ("bare link", "<https://example.com/a>", "https://example.com/a"),
    ("link label equals url", "<https://example.com|https://example.com>", "https://example.com"),
    ("mailto with label", "<mailto:ada@example.com|ada@example.com>", "ada@example.com"),
    ("mailto bare", "write <mailto:ada@example.com>", "write ada@example.com"),
    ("here", "<!here> standup", "@here standup"),
    ("channel broadcast", "<!channel>", "@channel"),
    ("everyone", "<!everyone|everyone>", "@everyone"),
    ("user group with label", "<!subteam^S123|@backend-team> please look", "@backend-team please look"),
    ("date token uses its label", "due <!date^1392734382^{date_short}|Feb 18, 2014>", "due Feb 18, 2014"),
    ("entities unescaped", "a &amp; b &lt;c&gt;", "a & b <c>"),
    ("several in one text", "<@U1> in <#C1|general>: <https://x.io|x>", "@Ada Lovelace in #general: x (https://x.io)"),
    ("plain text unchanged", "no markup here :tada:", "no markup here :tada:"),
    ("escaped angle brackets are not tags", "if a &lt; b then &lt;@U1&gt;", "if a < b then <@U1>"),
    ("empty text", "", ""),
]


@pytest.mark.parametrize(("name", "raw", "expected"), CASES, ids=[c[0] for c in CASES])
def test_a_ac_54_normalisation(name: str, raw: str, expected: str) -> None:
    """A-AC-54"""
    assert normalize_slack_text(raw, USERS, CHANNELS) == expected


def test_a_ac_54_has_at_least_fifteen_cases() -> None:
    assert len(CASES) >= 15


def test_works_without_lookup_tables() -> None:
    assert normalize_slack_text("<@U1> <#C1>") == "@U1 #C1"
