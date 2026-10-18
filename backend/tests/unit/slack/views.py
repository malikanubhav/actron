"""RequestDetail fixtures for the Slack block tests (test data only, spec B, B.C7 shape)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

RID = "req_01J9ZK3Q8M2V7XH4N5P6R7S8T9"
HASH = "a" * 64
SHA = "3f2a1c9d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39"

HEADLINES = {
    "Investigating": "Investigating. 4 graph queries so far.",
    "Needs your input": "Two earlier decisions affect this request. Two questions need your answer.",
    "Ticket ready": "Ticket drafted from your answers.",
    "Awaiting approval": "Ticket v2 is waiting for approval.",
    "Building": "Building. 3 of 14 tests passed.",
    "Needs attention": "The build needs attention.",
    "PR ready for review": "PR #18 is ready for review. 14 of 14 tests passed.",
    "Changes requested": "Changes requested. Building a new revision.",
    "Done": "Done. PR #18 was approved.",
    "Cancelled": "Cancelled by Priya.",
}

EVIDENCE = [
    {
        "evidenceId": "ev_1",
        "role": "similar_work",
        "nodeId": "github:pr:acme/app:12",
        "nodeType": "GithubPR",
        "title": "Add CSV export",
        "quote": "We tried CSV export before and rolled it back.",
        "source": {
            "type": "github_pr",
            "id": "12",
            "url": "https://github.com/acme/app/pull/12",
            "author": "dana",
            "at": None,
        },
        "confidence": 0.7,
        "tier": "MEDIUM",
        "path": [],
    },
    {
        "evidenceId": "ev_2",
        "role": "conflict",
        "nodeId": "slack:msg:C1:1.1",
        "nodeType": "SlackMessage",
        "title": "Finance only",
        "quote": "Invoice exports stay Finance-only.\nNo exceptions for project admins <yet> & later.",
        "source": {
            "type": "slack_message",
            "id": "C1:1.1",
            "url": "https://acme.slack.com/archives/C1/p11",
            "author": "Maya",
            "at": None,
        },
        "confidence": 0.92,
        "tier": "HIGH",
        "path": [],
    },
    {
        "evidenceId": "ev_3",
        "role": "constraint",
        "nodeId": "linear:issue:1",
        "nodeType": "LinearIssue",
        "title": "ENG-40 Export limits",
        "quote": None,
        "source": {
            "type": "linear_issue",
            "id": "1",
            "url": "https://linear.app/acme/issue/ENG-40",
            "author": None,
            "at": None,
        },
        "confidence": 0.8,
        "tier": "HIGH",
        "path": [],
    },
    {
        "evidenceId": "ev_4",
        "role": "owner",
        "nodeId": "x",
        "nodeType": "Person",
        "title": "Owner",
        "quote": "fourth",
        "source": {"type": "person", "id": "4", "url": None, "author": None, "at": None},
        "confidence": 0.5,
        "tier": "POSSIBLE",
        "path": [],
    },
]

QUESTIONS = [
    {
        "questionId": "q1",
        "text": "Should invoice exports stay Finance-only after this change?",
        "kind": "choice",
        "options": [
            {"value": "yes", "label": "Yes, keep Finance-only", "preselected": True},
            {"value": "no", "label": "No, project admins too", "note": "Needs a permission change"},
        ],
        "evidenceIds": ["ev_2"],
        "required": True,
        "answer": None,
    },
    {
        "questionId": "target_branch",
        "text": "Which branch should this change go into?",
        "kind": "choice",
        "options": [{"value": f"branch-{i}", "label": f"branch-{i}"} for i in range(7)],
        "evidenceIds": [],
        "required": True,
        "answer": None,
    },
    {
        "questionId": "q3",
        "text": "Which currency formats must the export keep?",
        "kind": "text",
        "options": [],
        "evidenceIds": [],
        "required": True,
        "answer": None,
    },
]

ALL_ACTIONS = [
    "answer",
    "edit_ticket",
    "approve_ticket",
    "pr_feedback",
    "approve_pr",
    "close_pr",
    "retry",
    "cancel",
]


def make_view(state: str = "Investigating", **over: Any) -> dict[str, Any]:
    final = state in ("Done", "Cancelled")
    view: dict[str, Any] = {
        "id": RID,
        "title": "Export invoices as CSV",
        "kind": "feature",
        "state": state,
        "label": None,
        "requester": {"personId": "p1", "userId": "u1", "name": "Priya", "avatarUrl": None},
        "source": "slack",
        "createdAt": "2026-10-18T09:00:00Z",
        "updatedAt": "2026-10-18T09:12:00Z" if final else "2026-10-18T09:03:00Z",
        "lastEvent": None,
        "pipelineStep": 1,
        "needsYou": False,
        "text": "Export invoices as CSV",
        "headline": HEADLINES[state],
        "purpose": "",
        "slack": {
            "channel": "C1",
            "threadTs": "1700000000.000100",
            "permalink": "https://acme.slack.com/archives/C1/p1700000000000100",
        },
        "findings": None,
        "evidence": [],
        "questions": [],
        "revisions": [],
        "currentRevision": None,
        "approvals": [],
        "builds": [],
        "pr": None,
        "investigation": None,
        "outcome": None,
        "answer": None,
        "allowedActions": ["cancel"],
    }
    if state in ("Needs your input", "Ticket ready", "Awaiting approval"):
        view["evidence"] = deepcopy(EVIDENCE)
        view["label"] = "conflict"
    if state == "Needs your input":
        view["questions"] = deepcopy(QUESTIONS)
        view["allowedActions"] = ["answer", "cancel"]
    if state in ("Awaiting approval", "Ticket ready"):
        view["currentRevision"] = {"n": 2, "hash": HASH}
        view["allowedActions"] = (
            ["edit_ticket", "approve_ticket", "cancel"]
            if state == "Awaiting approval"
            else ["edit_ticket", "cancel"]
        )
    if state in ("Building", "Needs attention", "PR ready for review", "Changes requested", "Done"):
        view["currentRevision"] = {"n": 2, "hash": HASH}
        view["builds"] = [
            {
                "id": "b1",
                "status": "running",
                "queuePosition": None,
                "branch": "actron/x",
                "baseSha": "b" * 40,
                "headSha": SHA,
                "testsPassed": 14,
                "testsFailed": 0,
                "attempts": 1,
                "startedAt": "2026-10-18T09:05:00Z",
                "finishedAt": None,
                "stopReason": None,
                "tokens": {"input": 1, "output": 1},
                "costUsd": 0.1,
                "report": None,
            }
        ]
        view["approvals"] = [
            {
                "id": "a1",
                "kind": "ticket",
                "target": HASH,
                "status": "accepted",
                "reason": None,
                "by": {"personId": "p2", "userId": "u2", "name": "Maya", "avatarUrl": None},
                "surface": "slack",
                "at": "2026-10-18T09:04:00Z",
            }
        ]
    if state in ("PR ready for review", "Changes requested", "Done"):
        view["pr"] = {
            "number": 18,
            "url": "https://github.com/acme/app/pull/18",
            "headSha": SHA,
            "state": "open",
            "targetBranch": "main",
        }
    if state == "PR ready for review":
        view["allowedActions"] = ["pr_feedback", "approve_pr", "close_pr", "cancel"]
    if state == "Needs attention":
        view["builds"][0].update(
            {
                "testsFailed": 2,
                "testsPassed": 12,
                "attempts": 2,
                "status": "failed",
                "stopReason": "tests_weakened",
            }
        )
        view["allowedActions"] = ["edit_ticket", "retry", "cancel"]
    if state == "Done":
        view["outcome"] = "approved"
        view["approvals"].append(
            {
                "id": "a2",
                "kind": "pr",
                "target": SHA,
                "status": "accepted",
                "reason": None,
                "by": {"personId": "p1", "userId": "u1", "name": "Priya", "avatarUrl": None},
                "surface": "ui",
                "at": "2026-10-18T09:12:00Z",
            }
        )
        view["allowedActions"] = []
    if state == "Cancelled":
        view["allowedActions"] = []
    view.update(over)
    return view
