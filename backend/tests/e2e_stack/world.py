"""The synthetic world the e2e stack serves (test data only, clearly fake names).

- Git: `acme/calc` (the synthetic repository the fake Pi knows: calc/ops.py with add and total, tests) as a
  local bare repository, and `acme/calc-fork` cloned from it as the push target.
- GitHub (fake): both repositories, one merged PR with a review that records a decision, one open issue.
- Slack (fake): workspace "Northwind Labs", channel #eng with a few messages, two people.
- Linear (fake): team ENG with states and labels.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.fakes.github import (
    FakeGithub,
    commit_json,
    issue_comment_json,
    review_comment_json,
    user,
)
from tests.fakes.linear import FakeLinear
from tests.fakes.slack import FakeSlack

REPO = "acme/calc"
FORK = "acme/calc-fork"
GITHUB_TOKEN = "ghp_e2eFAKE0000000000000000000000000000"
LINEAR_KEY = "lin_api_e2e_fake_key"
SLACK_BOT_TOKEN = "xoxb-test-token"
SLACK_TEAM = "T0001"
SLACK_CHANNEL = "C0E2EENG"
REQUESTER = "U0E2EDANA"
APPROVER = "U0E2ELEE"

OPS_PY = '''def add(a, b):
    return a + b


def total(items):
    result = 0
    for item in items:
        result = add(result, item)
    return result
'''
TEST_OPS_PY = '''from calc.ops import add, total


def test_add():
    assert add(2, 3) == 5


def test_total():
    assert total([1, 2, 3]) == 6
'''
README = """# calc

Small arithmetic helpers. `add` is part of the plugin API: keep its two arguments.
"""


def _ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(cwd: Path, *args: str, date: str | None = None) -> str:
    env = None
    if date:
        import os

        env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    out = subprocess.run(["git", "-c", "user.name=Dana Doe", "-c", "user.email=dana@acme.test",
                          "-c", "init.defaultBranch=main", *args], cwd=cwd, capture_output=True, text=True,
                         check=True, env=env)
    return out.stdout.strip()


def build_git(root: Path) -> dict[str, str]:
    """Fresh bare repositories under root/git/acme/. Returns the base sha of main."""
    git_root = root / "git"
    if git_root.exists():
        shutil.rmtree(git_root)
    work = root / "work"
    if work.exists():
        shutil.rmtree(work)
    (work / "calc").mkdir(parents=True)
    (work / "tests").mkdir()
    (work / "calc" / "__init__.py").write_text("")
    (work / "calc" / "ops.py").write_text("def add(a, b):\n    return a + b\n")
    (work / "calc" / "other.py").write_text('VERSION = "1"\n')
    (work / "pyproject.toml").write_text('[project]\nname = "calc"\nversion = "0.1.0"\n\n'
                                         '[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (work / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (work / "README.md").write_text(README)
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "Start calc with add", date=_ago(40))
    (work / "calc" / "ops.py").write_text(OPS_PY)
    (work / "tests" / "test_ops.py").write_text(TEST_OPS_PY)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "Add total built on add (#1)", date=_ago(20))
    git(work, "branch", "release-1")
    sha = git(work, "rev-parse", "HEAD")
    (git_root / "acme").mkdir(parents=True)
    origin = git_root / f"{REPO}.git"
    git(root, "clone", "-q", "--bare", str(work), str(origin))
    git(root, "clone", "-q", "--bare", str(origin), str(git_root / f"{FORK}.git"))
    return {"base_sha": sha, "git_root": str(git_root)}


def fill_github(fake: FakeGithub) -> None:
    dana, lee = user(101, "dana-doe"), user(102, "lee-park")
    fake.add_repo(REPO, repo_id=500, default_branch="main", owner_type="Organization")
    fake.add_repo(FORK, repo_id=501, default_branch="main", fork=True, parent=REPO, owner_type="Organization")
    fake.collaborators[REPO] = [dana, lee]
    fake.contributors[REPO] = [dict(dana, contributions=12), dict(lee, contributions=4)]
    merged, created = _ago(20), _ago(21)
    fake.add_pull(REPO, 1, title="Add total built on add", author=dana, updated_at=merged, created_at=created,
                  state="closed", merged=True, head_ref="total", head_sha="a" * 40, merge_commit_sha="b" * 40,
                  body="Adds total(items). total calls add for each item.", merged_by=lee, additions=9,
                  deletions=0, changed_files=2)
    fake.pr_files[REPO][1] = [
        {"filename": "calc/ops.py", "status": "modified", "additions": 6, "deletions": 0,
         "patch": "@@ -1,2 +1,8 @@\n def add(a, b):\n     return a + b\n+\n+\n+def total(items):\n+    ..."},
        {"filename": "tests/test_ops.py", "status": "added", "additions": 7, "deletions": 0,
         "patch": "@@ -0,0 +1,7 @@\n+from calc.ops import add, total"},
    ]
    fake.pr_commits[REPO][1] = [commit_json("a" * 40, "Add total built on add", "Dana Doe", "dana@acme.test", created)]
    fake.reviews[REPO][1] = [{"id": 3001, "state": "APPROVED", "body": "Approved. Keep add(a, b) exactly as it "
                              "is: plugins call it with two arguments.", "commit_id": "a" * 40,
                              "submitted_at": merged, "user": lee,
                              "html_url": f"https://github.com/{REPO}/pull/1#pullrequestreview-3001"}]
    fake.review_comments[REPO] = [
        review_comment_json(4001, 1, REPO, path="calc/ops.py", line=1,
                            body="We decided add keeps its two arguments; plugins depend on that signature.",
                            author=lee, commit_id="a" * 40, created=merged, review_id=3001)]
    fake.issue_comments[REPO] = [issue_comment_json(5001, REPO, 1, body="Merging.", author=dana, created=merged)]
    fake.issues[REPO][2] = {
        "id": 8002, "number": 2, "title": "calc has no subtract", "body": "Plugins need subtract next to add.",
        "state": "open", "user": dana, "created_at": _ago(5), "updated_at": _ago(5),
        "html_url": f"https://github.com/{REPO}/issues/2", "labels": [], "milestone": None, "assignees": [],
    }
    fake.labels[REPO] = [{"id": 1, "name": "enhancement", "color": "a2eeef", "description": "New feature"}]


def fill_slack(fake: FakeSlack) -> None:
    fake.add_user(REQUESTER, "dana", "Dana Doe", email="dana@acme.test")
    fake.add_user(APPROVER, "lee", "Lee Park", email="lee@acme.test")
    fake.add_channel(SLACK_CHANNEL, "eng", members=[REQUESTER, APPROVER, fake.bot_user])
    fake.add_message(SLACK_CHANNEL, "Reminder: add(a, b) is part of the plugin API. We keep its two arguments.",
                     user=APPROVER)
    fake.add_message(SLACK_CHANNEL, "Someone asked for subtract in calc; it should sit next to add.", user=REQUESTER)


def fill_linear(fake: FakeLinear) -> None:
    fake.api_key = LINEAR_KEY
    fake.add_team("lt1", "ENG", "Engineering")
    fake.add_user("lu1", "Dana Doe", "dana@acme.test", display="dana")
    fake.add_user("lu2", "Lee Park", "lee@acme.test", display="lee")
    fake.add_state("lt1", "ls1", "Todo", "unstarted", 1)
    fake.add_state("lt1", "ls2", "In Progress", "started", 2)
    fake.add_state("lt1", "ls3", "Done", "completed", 3)
    fake.add_label("lt1", "ll1", "actron")
    fake.add_issue("li1", "lt1", 1, "ENG", "Plugin API stays stable", updated_at=_ago(10),
                   description="add(a, b) is called by plugins. Do not change its arguments.", state="ls3",
                   creator="lu2")
