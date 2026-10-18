# Models and Jev

Actron asks models two kinds of things. Narrow judgments with a probability go to Jev (TypeSafe System One). Text that a person reads, and the investigator's tool calls, go to an LLM through LiteLLM. Every judgment has an LLM fallback and a conservative stub, so the product runs with no keys at all.

Code: `backend/actron/models/`. Spec: A13 and A.C4 in `specs/A-graph-and-ingestion.md`, PRD 10.

**Status on 18 Oct 2026:** live. Jev (`jev-1.13.0`) answers in the documented field names (live test A-AC-86 passes, about 350 to 400 ms per call). The LLM jobs run on `deepseek/deepseek-flash` (`MODEL_AGENT`, `MODEL_WRITING`, `MODEL_DECISION`) and `deepseek/deepseek-v4-pro` (`MODEL_CODING`), with `gemini/gemini-3.8-flash` as fallback.

**Real providers, learned in the live run:** DeepSeek accepts only `response_format: json_object`, not `json_schema`; for `deepseek/` models Actron sends `json_object` and puts the schema in the prompt. Gemini's free tier allows 20 requests per day per model, so it only works as a rare fallback. `deepseek-flash` answers a small call in about 1 to 3 s at about $0.00002 to $0.00008. Pi 1.3.0 knows `deepseek/deepseek-flash` and `deepseek/deepseek-v4-pro` natively (`DEEPSEEK_API_KEY`).

## Interface

`from actron.models import ...` (frozen in `specs/WORKSTREAMS.md`):

| Function | Kind | Model |
|---|---|---|
| `classify_message`, `is_approval`, `judge_link`, `judge_links`, `check_link`, `rank_candidates`, `judge_conflict`, `classify_request`, `needs_question`, `is_scope_change`, `feedback_kind`, `judge_supersession` | judgment, returns `Judgment` | Jev, then `MODEL_DECISION`, then stub |
| `extract_decision`, `extract_procedure` | JSON extraction | `MODEL_DECISION`, else no result |
| `write_questions`, `write_ticket`, `write_answer`, `summarize_findings` | text for people | `MODEL_WRITING`, else a deterministic template (marked stub) |
| `agent_completion(messages, tools)` | one tool-calling turn, returns `AgentTurn` | `MODEL_AGENT`; raises `ModelUnavailable` without a key |

Every job takes keyword `ws` and `request_id`, which go on the usage row.

`Judgment` fields: `job`, `answer` (the chosen option for `choice`; `True`/`False` at 0.5 for `noul`; the level index for `score`), `probability` (the `noul` value; for `choice` the probability of the chosen option; for `score` the score divided by the top level), `probabilities`, `confidence`, `model`, `provider` (`jev`, `llm` or `stub`), `cached`, `stub`.

## Jev transport

Plain `httpx` POST to `JEV_API_URL` (`https://api.typesafe.ai/v1/systemone`) with `Authorization: Bearer <TYPESAFE_API_KEY>` and body `{model, state, questions}`. Model: `JEV_MODEL` (default `jev-1.13.0`).

Why not the SDK: `typesafe-sdk` 0.7.5 works, but it uses its own `httpx2` fork, and its default retry policy does not retry 529. Plain httpx follows the spec's retry rules exactly and lets tests swap in a fake transport. The wire format is the same.

- Timeout: 20 s (`JevTimeout`).
- Retries: 429 and 529 only. Waits of 0.5, 1 and 2 s between at most 4 attempts. A `Retry-After` header raises a wait, capped at 4 s. After the last attempt: `JevRateLimited`.
- No retry, typed errors: 400 `JevBadRequest`, 401 `JevAuthError`, 413 `JevPayloadTooLarge`, 415 `JevUnsupportedMediaType`, 422 `JevValidationError`.
- A 200 whose answers do not match the documented shape raises `JevResponseError`.
- Every one of these errors moves the question to the LLM fallback.

Response parsing (from docs.typesafe.ai/api.md, read 17 Oct 2026): `answers[id].type`; `noul` → `answers[id].noul`; `choice` → `.choice`, `.probabilities`, `.confidence`; `score` → `.score`, `.legend`, `.probabilities`, `.confidence`; `usage.input_tokens`, `usage.output_tokens`. A `noul` answer has no `confidence`.

Independent questions over the same state go in one request: J3 for one text (all candidates), J5 (up to 20 candidates).

## Fallback order

1. **Jev**, when `TYPESAFE_API_KEY` is set.
2. **LLM** (`MODEL_DECISION`, then each model in `LITELLM_FALLBACKS`). The prompt (`prompts/judgment.md`) sends the same `state` and `questions` and asks for answers in Jev's answer shape. The reply must be valid JSON with an allowed option and a probability between 0 and 1. An invalid reply gets one retry with a reminder that says what was wrong. A second invalid reply goes to the stub. A provider error moves to the next model.
3. **Stub**: the most conservative answer, `stub: true`, confidence 0.0, model `stub`.

A model counts as available only when its provider key is set (`anthropic/` → `ANTHROPIC_API_KEY`, `openrouter/` → `OPENROUTER_API_KEY`, `gemini/` → `GEMINI_API_KEY`, `groq/` → `GROQ_API_KEY`, `deepseek/` → `DEEPSEEK_API_KEY`). Keys are passed to LiteLLM explicitly, because LiteLLM does not read `.env`.

LiteLLM call: `litellm.acompletion(model, messages, api_key, timeout=60, num_retries=2, drop_params=True, temperature=0, response_format={"type": "json_object"})`, or a `json_schema` response format for decision extraction.

## Every Jev call site

Cost: Jev charges $0.042 per million input tokens; output is free. The documented example of a one-question request used about 300 input tokens, so the estimates below add about 300 tokens of overhead to the JSON size. Accuracy: "stub" means it has not been measured with a real model (no key yet).

| # | Job | Runs when | Primitive | Threshold and use | Stub answer | Cost per call (est.) | Measured |
|---|---|---|---|---|---|---|---|
| J1 | `classify_message` | linking: every new or edited text | choice | `decision`/`proposal` ≥ 0.5 go to extraction; `decision` ≥ 0.7 plus a "decided" extraction = approved | `chatter`, 0.0 | 500-2,000 tokens, under $0.0001 | stub |
| J2 | `is_approval` | linking: replies to a decision or proposal | noul | ≥ 0.85 = approved, `APPROVED_IN`, `DECIDED_BY` | 0.0 | ~500 tokens, $0.00002 | stub |
| J3 | `judge_link`, `judge_links` | linking: candidates per text (one request per text) | noul per candidate | keep ≥ `LINK_KEEP_THRESHOLD` (0.6) | 0.0 | ~400 + 150 per candidate; 10 candidates ≈ 2,000 tokens, $0.00008 | stub (see eval) |
| J4 | `check_link` | linking: each model-made link | noul | < 0.5 delete, 0.5 to < 0.7 flag "possible", ≥ 0.7 keep | 0.5 (keep and flag; a stub never deletes) | ~400 tokens, $0.00002 | stub |
| J5 | `rank_candidates` | investigation: top 20 seeds | score per candidate (one request) | seeds at or above level 2 ("directly involved") | 0.0 | ~2,500 tokens for 20, $0.0001 | stub |
| J6 | `judge_conflict` | investigation: each decision on a seed | choice | `restricts` ≥ 0.8 conflict, 0.5-0.8 possible conflict | `unrelated`, 0.0 | ~450 tokens, $0.00002 | stub (see eval) |
| J6b | `judge_supersession` | linking: a new approved decision vs earlier ones on the same targets | choice | `replaces` ≥ 0.7 → `SUPERSEDES {scope}` | `unrelated`, 0.0 | ~450 tokens, $0.00002 | stub |
| J7 | `classify_request` | new request | choice | routes to build or Q&A | `feature` | ~400 tokens, $0.00002 | stub |
| J8 | `needs_question` | end of investigation | noul | decides "Needs your input" | 1.0 (ask when unsure) | ~600 tokens, $0.00003 | stub |
| J9 | `is_scope_change` | build: files outside the ticket | noul | ≥ 0.7 stops the build | 1.0 (stop when unsure) | 1,000-3,000 tokens, $0.0001 | stub |
| J10 | `feedback_kind` | PR feedback | choice | routes the feedback | `question` (never act without a person) | 800-2,000 tokens, $0.00008 | stub |

### Exact question JSON

The question id (`kind`, `approves`, ...) is for code only and is not used by the model. Placeholders are in angle brackets.

**J1 classify_message** (`source` is one of `slack`, `github_pr`, `github_review_comment`, `github_issue`, `linear_issue`, `linear_comment`)
```json
{"state": {"text": "<text>", "source": "slack", "thread_parent_text": null},
 "questions": {"kind": {"type": "choice", "instructions": "What is this text mainly doing in a software team's conversation?",
   "criteria": {"decision": "States how the software should or should not behave, or settles a choice",
                "proposal": "Suggests a way the software should behave, without settling it",
                "question": "Asks for information",
                "request": "Asks for a feature or change to be built",
                "bug_report": "Reports something broken",
                "status_update": "Reports progress or what someone did",
                "chatter": "Social talk, thanks, jokes or anything off-topic"}}}}
```
**J2 is_approval**
```json
{"state": {"decision": "<decision text>", "reply": "<reply text>", "reply_author_is_decision_author": false},
 "questions": {"approves": {"type": "noul",
   "instructions": "Does the reply explicitly approve or agree to adopt the decision in `decision`? Polite acknowledgement without agreement is not approval.",
   "criteria": {"true": "The reply clearly agrees the decision should be adopted", "false": "Anything else"}}}}
```
**J3 judge_link** (one candidate; `docstring` is cut to 400 characters)
```json
{"state": {"text": "<message text>", "candidate": {"kind": "function", "name": "<qualified name>", "path": "<path>",
           "signature": "<signature>", "docstring": "<docstring>"}},
 "questions": {"refers": {"type": "noul",
   "instructions": "Does `text` talk about the code or feature described in `candidate`, even if it does not name it?"}}}
```
**J3 batched** (`judge_links`, two or more candidates in one request)
```json
{"state": {"text": "<message text>", "candidates": [{"id": "c0", "kind": "function", "name": "...", "path": "...", "signature": "...", "docstring": "..."}]},
 "questions": {"c0": {"type": "noul",
   "instructions": "Does `text` talk about the code or feature described in candidate c0 in `candidates`, even if it does not name it?"}}}
```
**J4 check_link**
```json
{"state": {"quote": "<exact quote>", "claim": "<claim>"},
 "questions": {"supported": {"type": "noul", "instructions": "Does `quote` support `claim` exactly as stated?"}}}
```
**J5 rank_candidates** (ids `c0`..`c19`)
```json
{"state": {"request": "<request text>", "candidates": [{"id": "c0", "summary": "<summary>"}]},
 "questions": {"c0": {"type": "score", "instructions": "How relevant is candidate c0 in `candidates` to `request`?",
   "criteria": ["unrelated", "same area of the code", "directly involved in the change", "the exact place to change"]}}}
```
**J6 judge_conflict**
```json
{"state": {"request": "<request text>", "decision": {"statement": "<statement>", "quote": "<quote>", "status": "approved"}},
 "questions": {"relation": {"type": "choice", "instructions": "How does `decision` relate to what `request` asks for?",
   "criteria": {"restricts": "Doing the request as written would break or contradict the decision",
                "supports": "The decision agrees with or enables the request",
                "unrelated": "The decision does not affect the request",
                "superseded_by_request": "The request explicitly replaces the decision"}}}}
```
**J6b judge_supersession** (A12.4 "J6-style choice with state `{earlier, later}`")
```json
{"state": {"earlier": {"statement": "...", "quote": "...", "scope": "..."}, "later": {"statement": "...", "quote": "...", "scope": "..."}},
 "questions": {"relation": {"type": "choice", "instructions": "How does the `later` decision relate to the `earlier` decision?",
   "criteria": {"replaces": "The later decision replaces the earlier one, fully or for part of what it covers",
                "supports": "The later decision agrees with or extends the earlier one",
                "unrelated": "The two decisions are about different things"}}}}
```
**J7 classify_request**
```json
{"state": {"request": "<request text>"},
 "questions": {"kind": {"type": "choice", "instructions": "What kind of message is `request`?",
   "criteria": {"feature": "Asks for new behaviour", "bug": "Reports broken behaviour to fix",
                "question": "Asks for an explanation or information, not a change"}}}}
```
**J8 needs_question**
```json
{"state": {"findings_summary": "<findings summary>", "conflicts": ["<conflict>"], "max_criticality_percentile": 97.5},
 "questions": {"needs_input": {"type": "noul",
   "instructions": "Is a product decision from a person needed before this can be implemented safely?"}}}
```
**J9 is_scope_change**
```json
{"state": {"ticket": {"objective": "..."}, "diff_summary": "<diff summary>", "files_outside_affected_list": ["<path>"]},
 "questions": {"scope_change": {"type": "noul",
   "instructions": "Does the proposed change go beyond the approved acceptance criteria in `ticket`?"}}}
```
**J10 feedback_kind**
```json
{"state": {"feedback": "<feedback>", "ticket": {"objective": "..."}},
 "questions": {"kind": {"type": "choice", "instructions": "What is `feedback` asking for, given the approved `ticket`?",
   "criteria": {"code_change_within_scope": "Asks for a code change that stays within the approved ticket",
                "scope_change": "Asks for something the approved ticket does not cover",
                "question": "Asks for an explanation or information",
                "approval": "Approves the pull request as it is"}}}}
```

## Text jobs

| Job | Prompt | Without a model |
|---|---|---|
| `extract_decision` | `prompts/decision_extraction.md`, JSON schema `{is_decision, statement, quote, scope, status_hint}` | returns `None` (no decision is invented) |
| `extract_procedure` | `prompts/procedure_extraction.md`, `{area, steps[], testCommand}` | `None`; linking then uses a numbered-steps heuristic |
| `write_questions` | `prompts/questions.md` (max 3, evidence ids must exist in the findings) | one question per conflicting decision: "Should <decision> still hold for <request>?" |
| `write_ticket` | `prompts/ticket.md` (B.C5 shape, unknown ids dropped) | template: objective from the request, approved decisions as constraints (unless an answer lifts them), seeds as affected functions, covering tests with the procedure's test command |
| `write_answer` | `prompts/answer.md` | the evidence texts with their ids, or "Nothing in your history answers this yet." |
| `summarize_findings` | `prompts/situation.md` | "One earlier decision affects this request. ..." or "Nothing in your history touches this. Safe to continue." |
| `agent_completion` | system prompt `prompts/investigator.md` (used by W5) | raises `ModelUnavailable` |

`extract_decision` keeps a decision only when `quote` is an exact substring of the source text (only surrounding spaces are forgiven). A wrong quote gets one retry with a reminder, then the result is dropped (A-AC-84). The character span is returned as `quote_span`.

Prompts start with a version line. Prompts for text that people read carry the voice rules of PRD 13.4.

## Cache and usage

- Redis key `model:<job>:<sha256(model + canonical(state) + canonical(questions))>`, TTL 7 days. Jev answers use the model name `jev:<JEV_MODEL>`, LLM answers `llm:<first model in the chain>`. Stubs and errors are never cached. If Redis is down, the cache is skipped.
- Every call writes a `model_calls` row: job, provider, model, workspace, request, input and output tokens, latency, cost, `cached`, `stub`, `ok`, error. Failed attempts get their own row with `ok = false`.
- Cost comes from the price table in `models/usage.py` (USD per million tokens, estimates). A `MODEL_PRICES` setting will override it once W1 adds it (requested in BUILD-LOG).
- `usage.spent_today(ws)` sums today's cost (UTC) for the daily budget (spec B, B12a); `usage.over_budget(ws)` compares it with `ACTRON_DAILY_MODEL_BUDGET_USD`.

## Tests

| Area | Tests |
|---|---|
| Exact request JSON, A-AC-79 | `tests/unit/models/test_jev_requests.py` |
| Parsing documented answers, A-AC-79 | `tests/unit/models/test_jev_parse.py` |
| Retries, typed errors, fallbacks, A-AC-80/81 | `tests/unit/models/test_fallbacks.py` |
| Stubs, A-AC-82 | `tests/unit/models/test_stubs.py` |
| Cache, A-AC-83 | `tests/unit/models/test_cache.py` |
| Quote check, A-AC-84 | `tests/unit/models/test_extract_decision.py` |
| Usage rows and daily spend, A-AC-85 | `tests/unit/models/test_usage.py` |
| Real LiteLLM against a local OpenAI-compatible server | `tests/unit/models/test_litellm_wire.py` |
| Writing jobs and `agent_completion` | `tests/unit/models/test_writing.py` |
| Fake Jev matches the documented API | `tests/contract/test_jev_fake_server.py` |
| Live, A-AC-86 (skips without a key) | `tests/live/test_jev_live.py` |

Fakes: `tests/fakes/jev.py` (an `httpx.MockTransport` that validates requests and answers in the documented shape, with scripted status codes) and `tests/fakes/llm.py` (`FakeLLM` installed with `llm.configure(completion_fn=...)`, plus an OpenAI-compatible Starlette app for the wire test, plus the shared test fixtures).

Run: `cd backend && ACTRON_TEST_REDIS_DB=4 uv run pytest tests/unit/models tests/contract/test_jev_fake_server.py -q`. Live: add `-m live tests/live/test_jev_live.py` with `TYPESAFE_API_KEY` in `.env`.
