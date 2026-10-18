<!-- prompt: procedure_extraction, version: 1. Used by linking/procedures.py (spec A, A12.6) with MODEL_DECISION. -->
You read one text from a software team (a Slack message, a pull request template or description, or a doc
section) and decide whether it states how changes are made in some area of the code: steps to follow, a
command that validates a change, or files that must change together.

Rules:
- `area`: the component or path prefix the steps apply to (for example "src/cursor-doc"), or "" for the whole repository.
- `steps`: the steps in order, each a short plain sentence, taken from the text. Do not invent steps.
- `testCommand`: the command that validates changes, copied exactly from the text, or null when the text has none.
- If the text states no procedure, return an empty `steps` list and null `testCommand`.

Reply with one JSON object and nothing else:
{"area": "...", "steps": ["..."], "testCommand": "npm run unit-test"}

Text:
"""
{{text}}
"""
