# Executable worker and GitHub delivery

`RepositoryWorker` clones an exact full commit into persistent disposable artifacts. The
coding adapter receives the approved scope, joined evidence, preserved constraints,
feedback, and real prior check output. It proposes a patch; the trusted coordinator
applies it, creates a commit, and executes configured check IDs and the complete
`python -B -m unittest discover -s tests -v` suite. Commands in retrieved text never
become executable commands. The fixture uses the standard library; adding dependency
installation to the worker would require a separately controlled runner image.

Edits are restricted to `app/**/*.py` and new `tests/test_*.py` files. Existing
tests, dotfiles, approval/control documents and runner configuration are protected. New feature tests must use a new file. Once added, tests are protected
through later repair attempts. Git rejects path traversal; the worker rejects
symlinks. Coding processes have no workflow credentials, repository write mount or
merge capability. Git push and GitHub merge happen in a separate provider adapter.

## Model configuration

Build the checked-in coding image from the repository root:

```sh
docker build -f docs/coding.Dockerfile -t actron-coding .
docker pull python:3.12-slim
```

Set `OPENAI_API_KEY` and an explicitly selected `ACTRON_MODEL` with Responses API
access. Runtime wiring uses:

```python
coding = CommandCoding(
    ["python", "/opt/actron_model_cli.py"],
    image="actron-coding",
    environment=["OPENAI_API_KEY", "ACTRON_MODEL"],
)
worker = RepositoryWorker(repository_url, artifacts_directory, coding,
                          check_commands={"exports": ["python", "-B", "-m", "unittest",
                                                     "discover", "-s", "tests", "-v"]})
```

The default coding CLI makes a real request; it does not contain a solution patch.
Only `app/**/*.py` and `tests/**/*.py` from the disposable checkout are added as source
context. Evaluator answers and application control state are outside that checkout.
A token-count request checks input size before generation. A single generation call
uses the remaining total token budget as its output ceiling, with an additional
reserve. Actual provider usage and response IDs are retained. Truncated/invalid
responses fail explicitly, and unknown provider usage is labeled `tokens_unknown`.
There are no automatic provider retries. External adapters implementing `Coding`
must independently enforce the requested token ceiling at their provider.

The adapter follows the official [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
and [input-token counting API](https://developers.openai.com/api/docs/guides/token-counting).
`max_output_tokens` includes generated reasoning tokens; recorded total usage also
includes input tokens. Limits bound tokens rather than promising a currency budget
for every user-selected model.

## Execution and artifacts

The default Docker check runner has a read-only repository mount, no network,
non-root user, dropped capabilities, process/memory/CPU limits, and a small temporary
filesystem. The coding image also has a read-only checkout and no application/provider
credentials; only its explicitly configured model credentials are passed. Docker is
required; the worker fails when it is unavailable. `LocalRunner(trusted=True)` is an
explicit host-execution option for trusted fixtures and is not an isolation boundary.

Each operation gets a stable hashed artifact directory with `record.json`,
`commands.jsonl` and `checkout/`. The record retains base, changed commit, branch,
attempt commits, check commands, statuses, durations and raw output. `checks` contains
initial baseline and final-attempt results; `check_history` and `attempts` preserve
failed historical results. A repair starting from a verified owned failed commit
retains that failure as a `predecessor` check and validates the new commit afresh.
Scope-revision proposals return `scope_revision`, never rewritten acceptance criteria.

An OS lock grants one worker ownership. Completed operations return their persisted
result. A process interrupted before durable completion becomes `unknown`; retry
never silently starts a second owner. The artifact directory must be durable and
shared by the runtime instances using it. OS locks assume one host or a filesystem
with working advisory-lock semantics. Explicit new repair operations may fetch an
exact unpushed failed commit only from verified owned completed artifacts. Review
revisions receive a trusted `_execution_branch` through execution evidence and retain
the PR branch while changing the tested head.

## GitHub configuration

`GitHubPRs` requires an exact `owner/repository` plus a matching explicit
`dedicated_repository`. Push remotes are restricted to that repository's canonical
GitHub HTTPS/SSH URLs. Configure Git authentication outside the worker checkout;
API tokens are never passed to coding/check containers. The API token requires PR
write, contents write for merge, checks/status read, and administration read to
inspect branch protection; git push needs corresponding repository write access.

Configure branch protection/rulesets, the `suite` check, and at least one required
review in the dedicated repository. Missing/inaccessible protection metadata blocks
merge. The adapter reads both legacy branch protection and active branch rules,
combines required check names and producer-app IDs, and uses current-head checks and
latest reviewer states. Missing, pending, failed and successful results stay distinct.
Checks and reviews refresh immediately before merge. The merge request sends the
explicitly authorized SHA, enforcing the concurrent-head gate in GitHub itself.
These operations follow the official [pull request API](https://docs.github.com/en/rest/pulls/pulls),
[branch protection API](https://docs.github.com/en/rest/branches/branch-protection),
and [branch rules API](https://docs.github.com/en/rest/repos/rules).

PR bodies carry stable operation markers, ticket revision, constraints, evidence and
actual validation. After an uncertain response, `find` searches actual PR bodies
before creating anything. Review revisions push to the existing branch and append
fresh validation. Merge transport failures raise `UnknownOutcome`; reconciliation
reads actual PR merge state and resulting SHA instead of blindly repeating a merge.
A live smoke needs explicitly configured dedicated resources and human reviews;
contract fakes and deterministic patch stimuli do not establish live connectivity or
autonomous model performance.
