"""A-AC-86 (live, opt-in): one real Jev call per primitive returns a valid answer with the A.C4 fields.

Run: `uv run pytest tests/live/test_jev_live.py -m live` with TYPESAFE_API_KEY in .env.
"""

from __future__ import annotations

import pytest

from actron.config import get_settings
from actron.models import jev
from actron.models.questions import JevAsk

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _needs_key() -> None:
    get_settings.cache_clear()
    if not get_settings().TYPESAFE_API_KEY:
        pytest.skip("TYPESAFE_API_KEY is not set")
    jev.set_transport(None)


async def test_one_call_per_primitive() -> None:
    """A-AC-86: noul, choice and score answers parse; field names match A.C4."""
    ask = JevAsk(
        "live_check",
        {
            "text": "We decided to keep format-on-type off for Clojure files. Please do not change it."
        },
        {
            "is_decision": {"type": "noul", "instructions": "Does `text` state a decision?"},
            "kind": {
                "type": "choice",
                "instructions": "What is `text` mainly doing?",
                "criteria": {
                    "decision": "Settles a choice",
                    "question": "Asks for information",
                    "chatter": "Social talk",
                },
            },
            "firmness": {
                "type": "score",
                "instructions": "How firm is the statement in `text`?",
                "criteria": ["open", "leaning", "settled"],
            },
        },
    )
    resp = await jev.ask(ask)
    assert 0.0 <= resp.answers["is_decision"].value <= 1.0
    assert resp.answers["kind"].value in {"decision", "question", "chatter"}
    assert resp.answers["kind"].probabilities and resp.answers["kind"].confidence is not None
    assert 0.0 <= resp.answers["firmness"].value <= 2.0
    raw = resp.raw["answers"]
    assert set(raw["kind"]) >= {"type", "choice", "probabilities", "confidence"}
    assert set(raw["firmness"]) >= {"type", "score", "probabilities", "confidence"}
    assert "noul" in raw["is_decision"]
    assert resp.input_tokens > 0
