"""Ordered step names per source (spec A, A8 to A11). Plain data, so the workflow can import it safely."""

from __future__ import annotations

SOURCE_STEPS: dict[str, list[str]] = {
    "github": [
        "repo", "org", "contributors", "pulls", "pr_files", "pr_commits", "reviews", "review_comments",
        "issues", "issue_comments", "labels", "milestones", "releases", "branches", "check_runs",
        "workflow_runs",
    ],
    "slack": ["workspace", "users", "channels", "members", "history", "replies"],
    "linear": ["teams", "users", "states", "labels", "projects", "issues"],
    "slack_export": ["workspace", "users", "channels", "history", "events"],
    "code": [
        "clone_or_fetch", "walk_and_parse", "resolve", "link_tests", "documents", "manifests", "codeowners",
        "git_log", "hunks", "blame", "metrics",
    ],
}

# Incremental schedule interval in minutes (spec A, A11). Slack export is a one-off import: no schedule.
SCHEDULE_MINUTES: dict[str, int] = {"code": 15, "github": 5, "linear": 5, "slack": 10}
