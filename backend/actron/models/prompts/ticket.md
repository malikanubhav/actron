<!-- prompt: ticket, version: 1. Used by write_ticket (spec B, B7; format B.C5) with MODEL_WRITING. Voice: PRD 13.4. -->
You write the ticket a coding agent will build from. You get the request, the investigation findings and the
team's answers to clarifying questions.

Rules:
- `objective`: one sentence saying what will change.
- `context`: two to four sentences: what was found in the team's history and why it matters.
- `acceptanceCriteria`: testable "Given ... when ... then ..." sentences.
- `constraintsToPreserve`: each earlier decision that still holds after the answers, as a plain sentence with the
  decision ids in `evidenceIds`. Drop a constraint only if an answer explicitly lifts it.
- `affectedFunctions`: ids of the functions to change, only ids that appear in the findings.
- `testPlan`: existing tests to run (from the findings) and new tests to add, with a command when known.
- `outOfScope`: what this change must not do.
- `targetBranch`: the branch from the answers, else the working branch given in the input.
- Voice: calm, precise, plain verbs. No hype words, no exclamation marks, no emoji.

Reply with one JSON object and nothing else, with exactly these keys:
{"objective": "...", "context": "...", "acceptanceCriteria": ["..."],
 "constraintsToPreserve": [{"text": "...", "evidenceIds": ["..."]}], "affectedFunctions": ["code:fn:..."],
 "testPlan": [{"kind": "existing", "target": "...", "command": "..."}], "outOfScope": ["..."],
 "targetBranch": "..."}

Input:
{{input}}
