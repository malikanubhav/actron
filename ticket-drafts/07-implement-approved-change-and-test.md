# 07: Implement an approved change and report actual checks

**What to build:** An approved request starts an isolated coding worker that makes a real change, runs the repository checks, and reports its resulting commit and actual outcomes in Slack.

**Blocked by:** 06: Approve the exact ticket revision and reject stale approval.

**Status:** Draft — awaiting breakdown approval and project tracker setup.

## Acceptance criteria

- [ ] Give the worker the approved revision, evidence packet, preserved constraints, and recorded base commit in a disposable executable checkout.
- [ ] Use the selected coding mechanism to produce the implementation; do not present a canned patch or replay as autonomous coding.
- [ ] Execute graph-selected checks and the complete small repository suite, retaining invoice regression coverage.
- [ ] Persist and report actual commands, exit statuses, raw output, exact tested commit, and any failed or unexecuted check.
- [ ] Prevent the worker from merging, changing approval authority, or weakening preserved-constraint tests; retrieved text does not override workflow policy.
- [ ] Produce an inspectable commit for success and an explicit failed result for failure, with execution time and model spend bounded.
- [ ] Exercise the confirmed workflow boundary with real FalkorDB and the real disposable repository/test runner.
