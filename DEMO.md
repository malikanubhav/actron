# Demo script (3 minutes)

The story: an AI changes a shared helper and breaks a decision nobody remembered. Actron finds that decision in the graph before any code is written, asks the one question that matters, and builds the change with the evidence attached.

## Before recording

- `make up`, then sign in, connect the repository (Calva fork, working branch chosen), Slack and Linear. Wait for "Memory is up to date."
- Keys in `.env`: `GITHUB_TOKEN` (fork), Slack bot and app tokens, `LINEAR_API_KEY`, `TYPESAFE_API_KEY`, one model key with `MODEL_AGENT` and `MODEL_CODING`, `ACTRON_BOT_NAME`/`ACTRON_BOT_EMAIL`. Without them the flow still runs, but the build stops at `missing_identity` or `no_model_key`, and judgments are stubs.
- Seed one real decision in Slack before recording (a team member writes it in the channel, for example "We keep docFromTextNotation strict about line endings; the formatter tests depend on it."), so the graph has something to find. Do not invent data in the graph directly.
- Open three windows: Slack (desktop or phone), the Actron Request page, and the System view (`/app/system`).
- Practise once; then use **Replay** (`/app/requests/<id>/replay`) as the fallback if a live call is slow.

## Script

| Time | On screen | Say |
|---|---|---|
| 0:00–0:15 | Slack thread: the earlier decision message | "Six months ago this team decided how this helper must behave. It is in a Slack thread nobody will reread. Today someone asks an AI to change it." |
| 0:15–0:25 | Actron landing hero (the memory graph) | "Actron reads code, PRs, tickets and Slack into one FalkorDB graph and checks every request against it before an AI writes code." |
| 0:25–0:45 | In Slack: `/actron make docFromTextNotation accept Windows line endings` → the reply "On it. Investigating your request." with "Open in Actron" | "I ask in Slack, like I would ask a teammate." |
| 0:45–1:20 | Request page: tool-call cards streaming on the timeline (`search`, `find_symbol`, `callers`, `impact`, `decisions_for`), the canvas lighting up, the system map pulsing actron → FalkorDB | "The investigator chooses graph tools over MCP. Here it finds the function, its 969 callers, the tests that cover it, and the decision that constrains it. Each step is a real Cypher query." |
| 1:20–1:40 | Evidence tab: the decision card with the quote; press "Show path" and let the path trace hop by hop | "Every finding carries its source. This is the path from the request to the exact message where the team decided." |
| 1:40–1:55 | Phone (Slack): the question "Should docFromTextNotation stay strict for its current callers?" → tap an answer | "Because the graph found a conflict, Actron asks before building. I answer from my phone." |
| 1:55–2:10 | Request page: ticket v1 with constraints and affected functions; Approve shows `REVISION v1 · SHA-256 …`; approve | "The ticket is scoped by the graph. My approval is bound to this exact revision hash." |
| 2:10–2:40 | Build tab: steps streaming, the file being edited, tests ticking up, Pi's MCP calls; then PR tab with the diff and the constraints checklist | "Pi builds in a container with only a model key and the graph tools. The tests run offline. The PR lists the constraint it preserved and the test that proves it." |
| 2:40–2:55 | Graph explorer: the graph stats headline; then the two Cypher queries from the README | "Under it: 96 node types, real Calva code and history, PageRank for criticality, backwards traversal for impact, SPpaths for how things connect." |
| 2:55–3:00 | Request page, state "PR ready for review" | "Actron: the history checked, the question asked, the change built, and the path shown." |

## If something fails live

- Model or Slack slow: switch to the Replay of a finished request; it plays the recorded events, not invented ones.
- Build stops with `missing_identity` / `no_model_key`: show the Needs attention state; it is the designed behaviour without keys.
