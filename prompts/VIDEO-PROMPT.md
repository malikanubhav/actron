# Actron demo video: script, shot list and production prompt

For the team's use. Nothing here is published. Target: the FalkorDB Graph Hacks submission (deadline 18 Oct 2026, 11:59 PM IST).

## 0. What the hackathon asks for (rules page, read 18 Oct 2026)

- Submission needs: public repo; README with setup steps and the graph data model; the Cypher queries and graph algorithms the product depends on; a demo video of the working project; a live deployment (preferred) or full local setup steps; the tracks entered.
- The video length, format and hosting are not specified. Judging criteria are not published. Keep the video to about 5 minutes.
- AI coding assistants are allowed but must be disclosed, and the team must be able to explain the graph model, queries, architecture and decisions. The disclosure goes in the README, framed as AI-assisted development: the team designed the system, wrote the specs, reviewed and tested it. It is not repeated in the video.
- Data must be public, synthetic or your own. Calva (MIT) is public; the Slack history is our own or synthetic.
- Side prize: best blog post (draft at `docs/blog-post.md`).
- Tracks: Track 01 is the main entry. Tracks 02 and 03 are shown as secondary.

## 1. Shape of the video

About 5:00 in two parts. A voice-over (AI voice) runs the whole time. Everything on screen is our own: real screens of the running app, our own Slack, our own graph. No stock footage, no borrowed logos beyond the partner marks already in the app.

- Part 1, 0:00 to 2:30: the problem, why it matters, what Actron is, how FalkorDB makes it possible, the tracks.
- Part 2, 2:30 to 5:00: the product, from a Slack message to a merged PR, with launch-video motion: slow zooms into the part being described, callout labels, highlighted cursor, smooth cuts between screens.

Style: dark only, page colour `#0A0A0A`, same type as the app (Public Sans, Newsreader for headlines, JetBrains Mono for data). Accent yellow `#E4F24C` only for the evidence path and the one thing to look at. No emoji, no stock music with lyrics; a quiet low ambient bed at -24 dB under the voice. Captions on, burned in, sentence case.

## 2. Narration script

Plain spoken English, short sentences, natural pauses. `[pause]` means half a second. `[beat]` means one second of silence. Numbers are from the real Calva graph and the build report; re-check them against the live app the day you record (section 6).

### Part 1: the story (0:00 to 2:30)

**0:00 to 0:15, hook**
Ask an AI agent to change one function, and it will. [pause] What it won't tell you is that five other functions and hundreds of tests depend on it. Or that your team decided last month to keep that behaviour. [pause] Or who actually owns the code.

**0:15 to 0:45, the problem**
AI coding agents work from the code in front of them. But what your team knows lives somewhere else. [pause] The decision is in a Slack thread. The reason is in a review comment. The history is in git. The task is in a ticket. [pause] Nobody connects them. So the change passes its tests, and quietly breaks a promise. [beat] That costs rework, reverted pull requests, and trust in the agent.

**0:45 to 1:10, what we built**
So we built Actron. [pause] You ask for a change in Slack. Actron first investigates everything your team knows, in one graph. It asks only the questions the graph can't answer. Then it writes a versioned ticket, waits for a person to approve it, builds the change in a sandbox, and opens a pull request, with the evidence attached.

**1:10 to 2:00, why FalkorDB**
This only works because it's a graph. [pause] The real question is never "which file matches". It's: what is connected to this function, how, and how strongly. [pause] In FalkorDB, one query follows a Slack message to the decision, to the code it constrains, to the tests that cover it.
Our model has ninety-six node types across code, GitHub, Slack and Linear, under one ontology. For Calva, that's about twenty thousand nodes and seventy-seven thousand links. Five and a half thousand functions, with call links, test links, commits, and who wrote which line.
The agent gets twenty graph tools over MCP: callers, impact, shortest path, PageRank for criticality, decisions for a function. It chooses, and every call is visible. [pause] Hub functions answer in about half a second. Take FalkorDB away, and there is no product.

**2:00 to 2:30, tracks and honesty**
This is our entry for Track one, agents that act on connected data. It also covers memory, with a full replayable journal of every request and a separate graph per workspace. And company brain, with decisions traced back to the exact quote. [pause] It's backed by over fourteen hundred backend tests, running against real FalkorDB, Postgres and Temporal. Now, the product.

### Part 2: the demo (2:30 to 5:00)

**2:30 to 2:50, the request**
A teammate types a request in Slack: make docFromTextNotation accept Windows line endings. [pause] Actron answers in the thread straight away, and the same request appears in the app.

**2:50 to 3:20, the investigation**
This is the investigation, live. Each step is a real graph query. [pause] Search. Find the symbol. Decisions for it. Callers. Impact. [pause] On the right, the agent's path: from the request, to the function, to the test cluster. Solid links are explicit. Dashed ones are inferred. The yellow line is the evidence path.

**3:20 to 3:45, evidence**
The evidence tab shows what the graph found: five callers, nine hundred and sixty-four tests, and an earlier decision that may conflict. [pause] Every claim has a source. Click the decision, and you see the quote, from the Slack message it came from.

**3:45 to 4:05, questions**
Actron asks questions the graph couldn't settle. Should CRLF be kept, or normalised? [pause] The question lands in Slack, with buttons. Answer there, or in the app. It stays in sync.

**4:05 to 4:25, the ticket**
Now a versioned ticket: objective, acceptance criteria, affected functions, what is out of scope. [pause] Each version has a hash. Edit it, and the old approval is void. Only the right person, on the right version, can approve.

**4:25 to 4:50, the build**
Approval starts the build. Pi, the coding agent, runs in Docker. It has the graph tools, and a protocol: read first, edit, test. [pause] Tests run offline. If one fails, it repairs, up to twice. Then it opens a pull request on the fork.

**4:50 to 5:00, close**
The PR carries the diff, the tests, and the constraints it respected. Approve it, and the result is written back into the graph, so the next request starts smarter. [pause] Actron. Check what your team knows, before an agent writes code.

Total narration is about 750 words. Split it into the segment files in `video/narration/` (section 5) and generate each with the voice tool; the video timing follows the audio, not the other way round.

## 3. Shot list (animation direction)

Resolution 1920 x 1080, 30 fps (60 for zooms if the render is fast enough). Each shot lists the screen, what to zoom to, and the on-screen text.

| Time | Screen | Motion | On-screen text |
|---|---|---|---|
| 0:00 to 0:15 | Black, then a single line of code appearing: `docFromTextNotation(...)`. Lines draw out from it to five dots, then to hundreds | Slow dolly, nodes fade in one by one | "One function. Who depends on it?" |
| 0:15 to 0:45 | Four panels slide in: a Slack thread, a PR review comment, a git log, a ticket. Thin grey lines try to connect them and stop | Panels use our real screenshots; lines break | "Slack. Reviews. Git. Tickets." |
| 0:45 to 1:10 | Actron logo, then the pipeline `01 Investigate to 06 Review` drawing left to right | Wipe reveal | "Check first. Then build." |
| 1:10 to 2:00 | Graph explorer on real Calva: search, expand a node, links in per-source colours; then a Cypher snippet; then the tool list; then counts ticking up | Zoom 1.0 to 1.6 on a node cluster; counter animation | "96 node types", "~20k nodes · ~77k links", "20 MCP tools" |
| 2:00 to 2:30 | Three track badges, with Track 01 lit | Fade, subtle glow | "Track 01 · 02 · 03", "1,400+ backend tests" |
| 2:30 to 2:50 | Slack `#arctron-demo`: request typed, bot reply; cut to Home with the new row | Zoom on the thread, then the row's state chip | "Request" |
| 2:50 to 3:20 | Request page, timeline and graph | Zoom to the timeline tool cards, then to the graph evidence path; yellow path draws on | "Every step is a graph query" |
| 3:20 to 3:45 | Evidence tab, decision card with quote | Zoom on the quote; highlight the sentence | "Source: Slack · decision" |
| 3:45 to 4:05 | Slack buttons, then the Questions tab updating | Split screen: Slack left, app right | "Answer anywhere. Stays in sync." |
| 4:05 to 4:25 | Ticket tab, revision dropdown, the hash, the Approve button | Zoom on the hash; click Approve with a visible cursor ripple | "v1 · SHA-256 · approval bound to this version" |
| 4:25 to 4:50 | Build tab, steps ticking, tests passing, PR link | Zoom on the steps; speed up the waiting with a time-lapse indicator | "Pi in Docker · offline tests" |
| 4:50 to 5:00 | PR tab diff, then the GitHub PR in the browser, then the Actron logo | Zoom out to logo | "Actron" and the repo URL |

Rules for motion: ease-out curves, 300 to 600 ms per move, no bounce, no shake. One thing moves at a time. Zoom to the thing being said, not to decoration. Speed up waits (builds, model calls) and label them "sped up".

## 4. Slack: making the demo feel real

You do not need to give anyone access to your Slack. The bot token is already in `.env`.

- **History for the graph (synthetic, own data):** build a small Slack export (zip, our own fictional people, five or six channels' worth of two or three weeks of messages grounded in public Calva history: PR titles, issue topics). Import it with the built-in Slack export import (Connect, Slack export, spec A9a). This puts the people, threads and decisions in the graph for the evidence view. Use obviously fictional names and `.test` emails.
  - Include at least: a decision that matches the demo request (for example "We decided to keep the old test helper API; Windows line ending changes must not alter existing LF behaviour"), a review thread about CRLF, a ticket mention, a handoff note, and an owner mention.
- **The live channel:** keep `#arctron-demo` for what happens on camera: the request, Actron's thread replies, the questions with buttons. Post two or three realistic messages by hand before recording.
- **Real-looking members in the Slack UI (optional, only if time allows):** invite a few extra accounts to Heaven using plus addresses of one inbox (for example `you+maya@gmail.com`), accept each invite and set a name and photo. Slack treats them as separate people. The import above does not create Slack accounts, so the Slack screens would show only real members.
- Do not use real people's names or emails without their consent. Do not show the tokens, `.env` or the VS Code ports panel on camera.

## 5. Production prompt (for the agent that makes the video)

You are making the Actron demo video. Read this whole file first. Work unattended. Do not edit anything under `backend/` or `frontend/` except new files under `video/`. No commits.

1. **Pre-flight, do not film before it passes:**
   - `make up` is running, health green, Jev and the model report live.
   - One real request in workspace `dev` has run through approval, build and a PR on `vikram-choudhary03/calva`. If the build is still failing, say so in your report and film nothing for Part 2 yet; use the product's replay mode only if it is labelled "replay" on screen and in the narration.
   - Slack export imported (section 4) and `#arctron-demo` has the live thread.
2. **Capture, fully automatic (no manual screen recording, no OBS):** write a capture driver (`video/capture/run-demo.ts`) with Playwright that performs the whole demo against the real app by script, the way a person would: type the request, open the request page, click the tabs, answer the question, open the ticket, click Approve, watch the build, open the PR tab. Rules:
   - Viewport 1920 x 1080 with device scale factor 2, so zooms into the capture stay sharp.
   - For each row of section 3, save a full-resolution screenshot of the final state and a short video clip of the motion (timeline ticking, graph path drawing, build steps), using Playwright's recording or frame capture. Do not rely on one long recording.
   - Show the cursor: inject a visible cursor overlay and move it with eased paths, with a click ripple, so the composition can use it. Hide the dev badge, the footer's DEV marker if it distracts, and anything with a token.
   - Waiting time (investigation, build) is recorded in real time but is cut and sped up in the composition and labelled "sped up".
   - Sign in with Slack or the dev login, whichever works on the day; save the browser session state so the driver can re-run.
   - **Slack screens:** drive Slack in the web app with Playwright using a saved login. The human logs in once in the browser window the agent opens (never type or store a password), the agent saves the session state to a git-ignored file, and the driver reuses it. If Slack blocks automated browsing (a captcha or a login check), do not try to get around it: tell the human, and ask for four plain screenshots of the Slack thread taken by hand (request, questions with buttons, ticket message, PR message) and build those shots from the images.
   - Save everything to `video/captures/`, one folder per row of section 3, with a `manifest.json` that lists each file and what it shows.
3. **Compose:** build the video as code so it can be re-rendered. First choice: HyperFrames (HeyGen's open-source framework, Apache-2.0, HTML and CSS rendered to MP4 with headless Chrome and FFmpeg, built for coding agents; install its agent skills with `npx skills add heygen-com/hyperframes`; needs Node 22 or newer and FFmpeg; docs at hyperframes.heygen.com). Second choice: Remotion, only if its licence allows a team like ours (not checked). Last resort: plain ffmpeg. Check the version and install steps from the project's own README, not from memory. Each shot is one component with its timings in one `timeline.ts`. Implement the motion rules in section 3. Output `video/out/actron-demo-1080p.mp4` and a 720p copy.
4. **Narration:** write each segment of section 2 to `video/narration/NN-name.txt` and `video/narration/ALL.txt`, plain text without the stage marks, one paragraph per segment. The team generates the voice with a text-to-speech tool and drops the files in `video/audio/NN-name.mp3`. The composer reads the audio length of each file and stretches or holds shots to fit; until audio exists it uses the timings in section 2. Burn in captions from the narration text.
5. **Numbers:** read the numbers (nodes, links, functions, callers, tests) from the live app or the graph the day of recording and put them in `video/numbers.json`, which the on-screen text and the narration files use. If a number in section 2 differs, change the script, not the screen.
6. **Honesty rules:**
   - Do not claim anything that did not run live. Stubbed parts (anything marked STUB or fake) are not shown as working.
   - Show the real failure modes briefly if they occurred (a repair attempt) because it supports the story.
   - Do not mention how the code was written in the video. The AI-assistance disclosure the rules require goes in the README (section 7).
7. **Report:** a short `video/REPORT.md` with the render command, what was filmed live, what was sped up, what is missing, and a checklist of numbers to re-verify.

## 6. Day-of checklist

- [ ] Real request through PR completed; screenshots captured from that request.
- [ ] `video/numbers.json` re-read from the live app; narration matches.
- [ ] No tokens, `.env` or private data on any frame. Calva and our own Slack only.
- [ ] Voice generated; audio synced; captions checked.
- [ ] Video uploaded (YouTube unlisted or similar) and the link works while logged out.

## 7. Submission checklist (the repo, not the video)

- [ ] LICENSE added (still open in `NEEDS-FROM-USER.md`).
- [ ] README: setup steps, graph data model, the Cypher queries and algorithms the product depends on (see `docs/queries.md`, `docs/graph-model.md`), tracks entered, and a short "How this was built" section: the team designed the product, wrote the PRD, ontology and specs, directed an AI coding assistant (Claude Code) to implement them, then reviewed, tested and verified the result (say what you personally checked: the graph model, the queries, the live runs). Rule 12 means you must be able to explain all of it.
- [ ] No secrets in the repo (`.env` is git-ignored; scan before pushing).
- [ ] Live deployment URL, or local setup steps that work from a clean machine.
- [ ] Blog post posted (side prize), linked in the submission.
- [ ] Tracks entered: 01 (main), 02 and 03.

## 8. Voice: how to make the narration sound human

**Decision: the narration is the team's own voice (one person, the whole video).** The agent does not generate any voice. It writes the narration files, waits for the recordings in `video/audio/` (WAV or MP3, one per segment, named `NN-name`), reads each file's length, and fits the shots to the audio. Until the recordings exist, it renders a silent draft with captions using the script timings. The options below stay for reference if that changes.

Options, best first for this video:

1. **Your own voice.** Free and the most natural. Read the script from `video/narration/ALL.txt` in a quiet room, one segment at a time, close to a phone or headset mic. Record each segment as its own file, so one bad sentence means one re-take. Clean up with Audacity (noise reduction, normalise to about -16 LUFS). The rules want you to be able to explain the project, and your own voice makes that plain.
2. **Kokoro** (open-source, free, runs on your machine, Apache 2.0). Reported as the most natural of the free options; it does not clone voices. Good if you do not want to record.
3. **ElevenLabs.** The free plan allows personal use with attribution, not commercial use, as reported by third-party pages; the cheapest paid plan was listed at about $5 to $6 a month. Check their pricing page before relying on that. Use it only if you want a polished voice and accept the cost.
4. Not suitable: Wispr Flow turns your speech into text (dictation), and Bolna is a voice-agent platform for phone calls. Neither produces narration from a script.

Rules for any voice:
- One segment per file, named `NN-name`, matching `video/narration/NN-name.txt`.
- Keep the pace at about 150 words a minute. Leave half a second of silence at the end of each file; the composer trims it.
- Write words the way they should be said. Put these in the narration files (the on-screen captions keep the normal spelling):

| On screen | In the narration file |
|---|---|
| FalkorDB | Falkor D B |
| docFromTextNotation | doc from text notation |
| MCP | M C P |
| Pi (the coding agent) | Pie |
| SHA-256 | shah two fifty six |
| CRLF | C R L F |
| LF | L F |
| PageRank | page rank |
| Cypher | cypher |
| Temporal | temporal |
| Calva | Calva |
| tokens, `.ts`, file names | leave out unless essential |

- Read numbers as words ("nineteen thousand nine hundred and fifty two" is too long; say "about twenty thousand").
- Listen to every file once at normal speed with the screen shot list open, then fix the script, not the audio.

## 9. Recording: how, step by step

Use one of two ways. Take the first unless it is not working by early evening.

**A. The agent builds it (code-driven, repeatable, free).** Run the production prompt in section 5. It captures the real app with a scripted browser, composes the shots with zoom and callouts in HyperFrames (free, Apache-2.0), and renders the video. You then add your voice files and re-render. This is the same approach founders describe with Claude Code plus a code-based video tool: a storyboard first, scenes as code, then render-and-review rounds. They still choose the music, check every claim against the app, and fix the taste. A short ambient music bed is optional; use only music you have the right to use (for example a royalty-free track with its licence noted in `video/REPORT.md`).

**B. By hand (works without any code).**
1. Screen recorder: OBS Studio (free, Linux). For automatic zoom that follows the cursor, as in launch videos, try OpenScreen (free, MIT-licensed, lists Linux; directory sites say so, I have not tested it) or Recordly. Screen Studio is the well-known paid one but it is Mac-only.
   -  Scene: the browser window only, 1920 x 1080, 30 fps, cursor visible. Record the system audio off and the mic off; the voice is added later.
2. Browser: a clean profile, a dark theme, zoom 100%, no bookmarks bar, no extensions, no other tabs. Hide notifications. Use `https://cr65g885-3000.inc1.devtunnels.ms` or the deployed address only if the address bar is cropped out of the frame; otherwise show `localhost:3000`.
3. Do the demo twice as a rehearsal, then record in short takes, one per row of the shot list, not one long take. Move the cursor slowly and pause on what the narration will mention.
4. Slack: record the Slack window as its own take.
5. Edit in Kdenlive or DaVinci Resolve (both free, both run on Linux): put the takes on the timeline, add the narration, then zoom with keyframes (scale 100% to 150-170% over 400 to 600 ms with ease-out), cut waits with a speed-up label, add captions.
6. Export 1920 x 1080 H.264 MP4, about 8 to 10 Mbit/s. Upload as unlisted and test the link logged out.

Animation rules (same for A and B): one move at a time, ease-out, 300 to 600 ms, no bounce, zoom to what the voice is saying, label anything sped up, never show tokens or the address bar of a tunnel.

## 10. Order of work for tonight

1. Freeze the app (no more UI changes) and finish one real request through a PR.
2. Record or generate the voice for Part 1 first; it does not depend on the app.
3. Capture the app for Part 2 (the video agent, or by hand).
4. Compose, review at full speed once, fix, export.
5. Upload and put the link in the submission.
