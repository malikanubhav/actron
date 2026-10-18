"""Shared helpers for linking: text fields per label, authors, link records (spec A, A12)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from actron.graph import ids
from actron.graph.store import GraphStore

# TextSource group (core.json) with the properties that hold their text, in reading order.
TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "SlackMessage": ("text",),
    "LinearIssue": ("title", "description"),
    "LinearComment": ("body",),
    "GithubPullRequest": ("title", "body"),
    "GithubIssue": ("title", "body"),
    "GithubIssueComment": ("body",),
    "GithubReview": ("body",),
    "GithubReviewComment": ("body",),
    "GitCommit": ("message",),
    "CodeDocument": ("title", "text"),
}
TEXT_LABELS = frozenset(TEXT_FIELDS)
ACCOUNT_LABELS = frozenset({"SlackUser", "GithubUser", "LinearUser", "GitAuthor"})
CODE_LABELS = ("CodeFunction", "CodeClass", "CodeFile")
CONSTRAINABLE = frozenset({"CodeFunction", "CodeClass", "CodeFile", "CodeComponent", "Feature"})

# J1 `source` value per text label.
J1_SOURCE: dict[str, str] = {
    "SlackMessage": "slack",
    "GithubPullRequest": "github_pr",
    "GithubReviewComment": "github_review_comment",
    "GithubReview": "github_review_comment",
    "GithubIssue": "github_issue",
    "GithubIssueComment": "github_issue",
    "LinearIssue": "linear_issue",
    "LinearComment": "linear_comment",
    "GitCommit": "github_pr",
    "CodeDocument": "github_issue",
}

# Time property per text label (for decidedAt and signal windows).
TIME_FIELDS: dict[str, tuple[str, ...]] = {
    "SlackMessage": ("postedAt", "created_at"),
    "LinearIssue": ("createdAt",),
    "LinearComment": ("createdAt",),
    "GithubPullRequest": ("createdAt",),
    "GithubIssue": ("createdAt",),
    "GithubIssueComment": ("createdAt",),
    "GithubReview": ("submittedAt",),
    "GithubReviewComment": ("createdAt",),
    "GitCommit": ("authoredAt",),
    "CodeDocument": (),
}


@dataclass(frozen=True)
class CreatedLink:
    """A model-made link, handed to link checks (A12.5)."""

    rel: str
    from_label: str
    from_id: str
    to_label: str
    to_id: str
    quote: str
    claim: str
    method: str = "inferred"


@dataclass
class TextNode:
    id: str
    label: str
    text: str
    props: dict[str, Any] = field(default_factory=dict)

    @property
    def deleted(self) -> bool:
        return bool(self.props.get("deleted"))


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def label_of(node_id: str) -> str | None:
    try:
        return ids.label_of(node_id)
    except ids.InvalidId:
        return None


def is_version(node_id: str) -> bool:
    """Previous-version nodes (`...@v<n>`) are history, never linked themselves."""
    return re.search(r"@v\d+$", node_id) is not None


def text_of(label: str, props: dict[str, Any]) -> str:
    parts = [str(props[f]) for f in TEXT_FIELDS.get(label, ()) if props.get(f)]
    return "\n\n".join(parts)


def load_texts(
    store: GraphStore, node_ids: list[str], *, include_deleted: bool = True
) -> list[TextNode]:
    """Load text nodes by id (unknown ids and non-text labels are skipped)."""
    by_label: dict[str, list[str]] = {}
    for nid in node_ids:
        lbl = label_of(nid)
        if lbl in TEXT_LABELS and not is_version(nid):
            by_label.setdefault(lbl, []).append(nid)
    out: list[TextNode] = []
    for lbl, group in by_label.items():
        rows = store.query(
            f"UNWIND $ids AS nid MATCH (n:`{lbl}` {{id: nid}}) RETURN n",
            {"ids": group},
            read_only=True,
        )
        for row in rows:
            props = dict(row["n"])
            if not include_deleted and props.get("deleted"):
                continue
            out.append(TextNode(props["id"], lbl, text_of(lbl, props), props))
    order = {nid: i for i, nid in enumerate(node_ids)}
    out.sort(key=lambda t: order.get(t.id, 0))
    return out


def time_of(node: TextNode) -> str | None:
    for f in TIME_FIELDS.get(node.label, ()):
        if node.props.get(f):
            return str(node.props[f])
    return None


def is_bot_message(node: TextNode, bot_user_ids: set[str] | None = None) -> bool:
    """Bot and Actron messages never yield decisions (A-AC-56)."""
    p = node.props
    if node.label == "SlackMessage":
        if p.get("botId") or p.get("subtype") in ("bot_message", "bot_add"):
            return True
        if bot_user_ids and p.get("userId") in bot_user_ids:
            return True
    return False


def author_account(store: GraphStore, node: TextNode) -> tuple[str, str] | None:
    """(account label, account id) of a text's author, when the graph knows it."""
    if node.label == "SlackMessage":
        rows = store.query(
            "MATCH (m:SlackMessage {id: $id})-[:POSTED_BY]->(u:SlackUser) RETURN u.id AS id LIMIT 1",
            {"id": node.id},
            read_only=True,
        )
        if rows:
            return "SlackUser", str(rows[0]["id"])
        if node.props.get("userId"):
            return "SlackUser", ids.slack_user(str(node.props["userId"]))
        return None
    patterns = {
        "LinearComment": "MATCH (n:LinearComment {id: $id})-[:CREATED_BY]->(u:LinearUser)",
        "LinearIssue": "MATCH (n:LinearIssue {id: $id})-[:ISSUE_CREATED_BY]->(u:LinearUser)",
        "GithubReviewComment": "MATCH (n:GithubReviewComment {id: $id})-[:REVIEW_COMMENT_BY]->(u:GithubUser)",
        "GithubIssueComment": "MATCH (n:GithubIssueComment {id: $id})-[:COMMENT_BY]->(u:GithubUser)",
        "GithubPullRequest": "MATCH (n:GithubPullRequest {id: $id})-[:OPENED_BY]->(u:GithubUser)",
        "GithubIssue": "MATCH (n:GithubIssue {id: $id})-[:ISSUE_OPENED_BY]->(u:GithubUser)",
        "GithubReview": "MATCH (n:GithubReview {id: $id})-[:REVIEWED_BY]->(u:GithubUser)",
        "GitCommit": "MATCH (n:GitCommit {id: $id})-[:AUTHORED_BY]->(u:GitAuthor)",
    }
    cypher = patterns.get(node.label)
    if not cypher:
        return None
    rows = store.query(
        cypher + " RETURN u.id AS id, labels(u)[0] AS l LIMIT 1", {"id": node.id}, read_only=True
    )
    if not rows:
        return None
    return str(rows[0]["l"]), str(rows[0]["id"])


def person_of(store: GraphStore, account: tuple[str, str] | None) -> str | None:
    if account is None:
        return None
    rel = {
        "SlackUser": "IS_SLACK_USER",
        "GithubUser": "IS_GITHUB_USER",
        "LinearUser": "IS_LINEAR_USER",
        "GitAuthor": "IS_GIT_AUTHOR",
    }[account[0]]
    rows = store.query(
        f"MATCH (p:Person)-[:HAS_IDENTITY]->(:Identity)-[:{rel}]->(u:`{account[0]}` {{id: $id}}) "
        "RETURN p.id AS id LIMIT 1",
        {"id": account[1]},
        read_only=True,
    )
    return str(rows[0]["id"]) if rows else None


def excerpt(text: str, start: int, end: int, context: int = 60) -> str:
    """The matched span with up to `context` characters on each side (A12.2 quote)."""
    return text[max(0, start - context) : min(len(text), end + context)].strip()


def default_repo(store: GraphStore) -> str | None:
    """The workspace's repository (owner/name, lowercased) for bare `#123` references."""
    from actron.config import get_settings

    configured = get_settings().GITHUB_REPOSITORY
    if configured:
        return configured.strip().lower()
    rows = store.query("MATCH (r:CodeRepository) RETURN r.id AS id LIMIT 2", read_only=True)
    if len(rows) == 1:
        return str(rows[0]["id"]).removeprefix("code:repo:")
    return None
