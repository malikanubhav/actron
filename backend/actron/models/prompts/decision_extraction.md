<!-- prompt: decision_extraction, version: 1. Used by extract_decision (spec A, A12.4) with MODEL_DECISION. -->
You read one message from a software team (Slack, a pull request, a review comment, an issue or a ticket) and
decide whether it states a decision about how the software should or should not behave.

Rules:
- A decision settles a choice or sets a rule ("exports stay CSV only", "we will not format on paste").
  A proposal suggests one without settling it. Questions, thanks and status updates are not decisions.
- `statement`: the decision in one plain sentence, in your own words, present tense.
- `quote`: copy the exact words from the message that state the decision. Copy them character for character,
  including punctuation and case. Do not join separate parts, do not fix typos, do not add or drop words.
- `scope`: where the decision applies, in a few plain words (a feature, a file, a command), or "" if unclear.
- `status_hint`: "decided" only if the text itself says the choice is settled ("we decided", "going with",
  "approved", "let's do X" by the person who owns it); otherwise "proposed".
- If the message holds no decision or proposal, set `is_decision` to false and leave the other fields empty.

Reply with one JSON object and nothing else:
{"is_decision": true, "statement": "...", "quote": "...", "scope": "...", "status_hint": "decided"}

Message:
"""
{{text}}
"""
