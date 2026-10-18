# Blog prize: what past WeMakeDevs winners did, and our outline

Research done 18 Oct 2026. The Graph Hacks blog prize is AirPods 5, one winner ("document your process and turn it into a blog: what you built, how FalkorDB fits in, what you learned"). Judging criteria for blogs are not published.

## What I could and could not find

I found the winner of two past WeMakeDevs blog prizes. I could not read either winning post: Medium returns 403 to every automated request, and I did not work around that. So what follows about those two comes from their titles, the contest rules and the organisers' own advice. Where I describe how a post is written, I say which post I actually read.

| Hackathon | Blog prize | Winner | Post | Read? |
|---|---|---|---|---|
| Cognee, "The Hangover Part AI" (Jun 29 to Jul 5, 2026) | Best Blog, Keychron keyboard | Mahimai Raja J | "Your voice agent forgets you the moment you hang up. I gave it a memory." (Medium) | Title only; read the project's README instead |
| SigNoz, "Agents of SigNoz" | Pre-Event Blog Prize, AirPods Pro 3 or Beats | Pooja Bhavani | "How I self-hosted SigNoz on AWS EC2 to monitor Claude, one sneaky IP timeout" (Medium) | Title only |
| Agent Harness (TrueFoundry), Aug 24 to 30, 2026 | "Field Report", Best Blog Post, Keychron | Not found | n/a | n/a |
| Bharat Builds First Commit, Sep 17 to 20, 2026 | Five winning blogs, Logitech keyboard each | Not found | n/a | n/a |

Links:
- Cognee winners page: https://archive.wemakedevs.org/hackathons/cognee
- Cognee winner's post: https://mahimairaja.medium.com/your-voice-agent-forgets-you-the-moment-you-hang-up-i-gave-it-a-memory-90ef8fdc8327
- Cognee winner's project: https://github.com/mahimairaja/realtyRecall/
- SigNoz blog list (500+ posts, one marked winner): https://archive.wemakedevs.org/hackathons/signoz/projects/blogs
- SigNoz winner's post: https://medium.com/@poojabhavani19/how-i-self-hosted-signoz-on-aws-ec2-to-monitor-claude-one-sneaky-ip-timeout-965984f5dc92
- Organisers' advice for the Field Report: https://wemakedevs.org/blogs/agent-harness-hackathon-kick-off

I also read one strong, open post from the same SigNoz contest that was not marked as the winner, as a model of a "field report":
- "Our incident response agent got the root cause wrong 7 times out of 12. It still never made a bad..." by Aayush Bharadva: https://dev.to/aayush-bharadva/our-incident-response-agent-got-the-root-cause-wrong-7-times-out-of-12-it-still-never-made-a-bad-42ao

## What the winners and the rules tell us

Facts:
1. **The organisers say what they want.** Their advice for a good write-up is: the problem you chose, how you built it and how the sponsor's tool helped, what broke along the way, and what you learned (or "what you chose, what broke and what you would do differently"). The Cognee rule says: about your build, your journey, or how the tool gives the agent memory. The SigNoz rule says: write about the feature you like most, and it must be on a blogging platform such as Medium, Dev.to or Substack, not LinkedIn.
2. **Both winning titles are a first-person story with one concrete image.** "I gave it a memory" and "one sneaky IP timeout" name a specific thing that happened. Neither title is a product pitch or a feature list.
3. **The winning Cognee post sits beside a project that is small and finished.** Its README (which I read) is a short pitch with a one-line tagline, five stack badges, jump links, a short "run it" with `make up`, and a one-paragraph architecture summary naming the memory layer as the system of record. It has no diagrams or numbers, so a blog does not need either to win. Take that with care: it is one example, and I did not see the blog.
4. **The sponsor tool is the centre of the story, not a mention.** In both winning titles and in the README, the tool is the thing the story turns on (memory, observability).

Inference (my reading, not stated by anyone):
- Winners likely read as honest and specific: a concrete moment of failure or surprise, told in the first person.
- A reader should be able to see exactly what the sponsor tool did that nothing else could.

What a strong field report looks like, from the one post I read in full (Bharadva, about 2,900 words):
- Opens with a surprising admission and a number: "The model was wrong more often than it was right, and the system still did the right thing almost every time."
- Sections: The setup; the bug that cost me my first design; getting the data to answer a question the model can't be trusted with; three afternoons I am not getting back; two smaller things worth copying; the numbers, with the caveats attached; if I were starting this over; where this leaves me.
- Seven code blocks, two tables, three screenshots, no diagrams. Real numbers with the denominators (5 of 12, not "mostly").
- Failures are specific and first-person, and framed as lessons. A "what the results don't show" list. Ends with one blunt, quotable rule, then repo and walkthrough links, and a one-line note that AI assisted the coding.
- The limitation is that this post was not marked as the winner. Use it as a model of craft, not proof of what wins.

## Our outline

Working title (pick one):
- "The agent that checks your Slack before it touches your code"
- "We gave a coding agent a memory of what our team decided, and a graph to find it"
- "The test that was caught by a graph: how a request about line endings turned into a question about 964 tests"

Where to publish: dev.to or Medium (Medium blocks scrapers, so judges using a browser are fine, but dev.to is easier to link and embed). Do not use LinkedIn alone.

Length: 1,800 to 2,500 words. Use real screenshots from the running app (ours only).

1. **Opening (150 words): one real moment.** The request "make docFromTextNotation accept Windows line endings". Before any code, Actron asked: "It's called from 5 functions and 964 tests. Should its current behaviour stay the same for them?" Then the point: a coding agent can read the repo; it cannot read what the team decided. Include the first screenshot: the request page with the evidence path.
2. **The problem we chose (200).** Decisions in Slack, reasons in reviews, owners in blame, scope in tickets, and nothing connecting them. What it costs. Keep it to one example, not three.
3. **The setup (200).** Five sources into one FalkorDB graph per workspace: code, git, GitHub, Slack, Linear. A fixed ontology: 96 node types, 275 link types, every link tagged with how it was made and a confidence. Calva as the demo repo. Table of counts (nodes, links, functions, `CALLS`, `TESTS`, commits).
4. **Why it had to be a graph (300): the heart of the post.** Three queries that only make sense as graph traversals, each with the Cypher and one screenshot or tiny diagram:
   - callers to depth N and impact (backwards variable-length matches);
   - "how are these two things connected" (`algo.SPpaths`, both directions);
   - criticality with `algo.pageRank`, which changed what the agent asks.
   State what would be needed without FalkorDB. This answers the rule "if it works without the graph, the graph is decoration".
5. **The agent picks its tools (200).** 20 graph tools over MCP, each call visible in the UI. How findings change behaviour (a decision means a question to a person; a hub function means a question about callers). Screenshot of the tool-call timeline.
6. **What broke (400): the part judges remember.** Use the real entries from `docs/falkordb.md` and `BUILD-LOG.md`, each with what we saw, why, and the fix:
   - the planner scanning every function when ids were unwound inside a pattern (2.3 s down to 4 ms, impact from timeout to 0.12 s);
   - `algo.BFS` following outgoing links only, and `shortestPath` being directed and allowed only in `WITH`/`RETURN`;
   - the append-only file that crashed the server after a graph with a unique constraint was dropped, and the volume that had to be abandoned;
   - tree-sitter positions returning garbage above 256 until we used tuple indexing (a real crash during the build);
   - something from the live run: the real model's failures, the Gemini daily limit, DeepSeek rejecting `json_schema`.
   Give numbers. Be plain about what was your mistake.
7. **The numbers, with caveats (200).** Table: load test (p95 for shared query and impact, 4,609 writes a second, zero errors), the 1,400+ backend tests, quality of link and conflict judgments with the real model (explicit refs 1.00 precision and recall; conflict at 0.8 over-called, 8 false positives of 21) and a "what these numbers don't show" list. State that the labelled set is small and was written alongside the prompts.
8. **Two windows, one request (150).** Slack and the web app as two views of one Temporal workflow; approvals bound to a SHA-256; a stale approval refused. One screenshot of the same request in Slack and in the app.
9. **If we started over (150).** Three things: calibrate thresholds on real model answers; anchor every traversal by id from day one; test persistence by restarting the server before building on it. Plus what is not done yet.
10. **How we built it (80).** The AI-assistance disclosure, framed as the team did it: designed the product, wrote the PRD, ontology and specs, directed an AI coding assistant to implement them, then reviewed and verified with tests and live runs. Keep it factual and short, as the rules ask.
11. **Links (30):** repo, demo video, live URL, README graph-model section.

Style rules (from the winning pattern, as far as I can tell):
- First person, plural "we". Short paragraphs. One idea per section.
- Every claim has a number or a screenshot. Give the denominator.
- Name what failed before what worked.
- No product-pitch language ("revolutionary", "seamless", "leverage"). No emoji.
- End on one blunt, quotable lesson rather than a summary.

Existing draft: `docs/blog-post.md` already has sections 3, 4, 5, 6 and 8 in rough form with real numbers. The rewrite should keep those numbers, add the opening moment, the failure stories, the caveats table, the "if we started over" section and the screenshots, and cut anything that reads like a feature list.

## Before publishing

- Re-check every number against the live app and `docs/falkordb.md` on the day.
- No tokens or private data in any screenshot. Calva and our own Slack only.
- Link the post from the Graph Hacks submission and the README.
- The prize page does not say how blog entries are submitted; check the submit page on the day.
