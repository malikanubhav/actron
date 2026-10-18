# Read-aloud script (your voice)

Record this after the video draft exists, with the video playing silently on a screen in front of you. Read each segment while you watch its shots, and match the target length. If a line does not feel natural in your mouth, say it your own way, keep the meaning, and tell the video agent so the captions are changed to match.

How to record:
- One file per segment, named as below (`01-hook.wav`, and so on). Save them in `video/audio/`.
- A quiet room, close to the mic (about a hand's width), a soft cloth nearby to cut the echo. Do a 10-second test first and listen on headphones.
- Pace is about 150 words a minute. `...` is a short pause. A blank line is a breath. Leave one second of silence at the start and the end of every file.
- Read the numbers as written. Do not read the bracketed notes aloud.
- Before you record, check the numbers against the live app on the day: the node and link counts, the five callers, the 964 tests.

## Part 1: the story

**01-hook** (about 15 seconds)

Ask an AI agent to change one function, and it will.
But it won't tell you that five other functions and hundreds of tests depend on it...
or that your team decided to keep that behaviour...
or who owns the code.

**02-problem** (about 30 seconds)

AI coding agents work from the code in front of them.
But what your team knows lives somewhere else.

The decision is in a Slack thread. The reason is in a review comment. The history is in git, and the task is in a ticket.
Nobody connects them.

So the change passes its tests... and quietly breaks a promise.
That means rework, reverted pull requests, and less trust in the agent.

**03-built** (about 25 seconds)

So we built Actron.

You ask for a change in Slack. Actron first investigates everything your team knows, in one graph.
It asks only what the graph can't answer.
Then it writes a versioned ticket, waits for a person to approve it, builds the change in a sandbox, and opens a pull request with the evidence.

**04-falkordb** (about 50 seconds)

This only works because it's a graph.

The real question is never "which file matches". It's: what is connected to this function, how, and how strongly.
In FalkorDB, one query can follow a Slack message to a decision, to the code it constrains, to the tests that cover it.

Our model has ninety-six node types, across code, GitHub, Slack and Linear.
For Calva, that's about twenty thousand nodes and seventy-seven thousand links... with call links, test links, commits, and who wrote each line.

The agent gets twenty graph tools over M C P: callers, impact, shortest path, page rank for how critical a function is, and decisions for a function.
It picks them, and every call is visible.
Busy functions answer in about half a second.

Take FalkorDB away... and there's no product.

**05-tracks** (about 30 seconds)

This is our entry for Track one: agents that act on connected data.

It also touches memory, with a replayable journal for every request and a separate graph for each workspace.
And company brain, with decisions traced back to the exact quote.

It's backed by over fourteen hundred backend tests, running against real FalkorDB, Postgres and Temporal.
Now... let's see it work.

## Part 2: the demo

**06-request** (about 20 seconds)

A teammate types a request in Slack: make doc-from-text-notation accept Windows line endings.
Actron replies in the thread straight away... and the same request shows up in the app.

**07-investigation** (about 30 seconds)

Here's the investigation, live. Every step is a real graph query: search, find the function, decisions, callers, impact.

On the right is the agent's path, from the request to the function to the tests.
Solid links are explicit. Dashed ones are inferred.
And the yellow line... is the evidence path.

**08-evidence** (about 25 seconds)

The evidence tab shows what the graph found: five callers, nine hundred and sixty-four tests, and an earlier decision that may conflict.

Every claim has a source.
Open the decision, and you see the exact quote, from the Slack message it came from.

**09-questions** (about 20 seconds)

Actron asks the questions the graph couldn't settle.
Should C R L F be kept, or turned into L F?

The question lands in Slack, with buttons.
Answer there, or in the app. They stay in sync.

**10-ticket** (about 20 seconds)

Now a versioned ticket: the objective, the acceptance criteria, the functions affected, and what's out of scope.

Each version has a hash. Edit it, and the old approval no longer counts.
Only the right person can approve the right version.

**11-build** (about 25 seconds) [Record this only if the build really ran. Otherwise skip it and say so in the close.]

Approving starts the build.
Pi, the coding agent, runs in Docker, with the graph tools and a simple protocol: read, edit, test.
Tests run offline. If one fails, it repairs, up to twice.
Then it opens a pull request on the fork.

**12-close** (about 15 seconds)

The pull request carries the diff, the tests, and the constraints it respected.
Approve it, and the result is written back to the graph... so the next request starts smarter.

Actron. Check what your team knows... before an agent writes code.

## After you record

- Listen to each file once with the video playing. Re-record only the segments that sound off.
- The close may run a few seconds over; the video agent will extend the last shot to fit.
- Send the files to the video agent in `video/audio/`.
