"""Edit history for records whose text people change (spec A, A4 "Versions and tombstones").

Before an edit overwrites the main node, the current state is copied to `<id>@v<n>` (same label,
`version = n`). The main node points at the newest copy with the version relationship, and each copy
points at the one before it, so the chain reads newest to oldest:

    main (version 3) -> @v2 -> @v1

Slack messages use PREVIOUS_VERSION. Linear issues and comments use ISSUE_PREVIOUS_VERSION and
COMMENT_PREVIOUS_VERSION. Other sources keep only the latest text.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow, to_graph_value

VERSION_RELS: dict[str, str] = {
    "SlackMessage": "PREVIOUS_VERSION",
    "LinearIssue": "ISSUE_PREVIOUS_VERSION",
    "LinearComment": "COMMENT_PREVIOUS_VERSION",
}


class NodeNotFound(LookupError):
    """The node to version does not exist."""


def is_version_id(node_id: str) -> bool:
    """True for the id of a stored previous version (`...@v<n>`)."""
    base, sep, tail = node_id.rpartition("@v")
    return bool(sep and base and tail.isdigit())


def version_node(store: GraphStore, node_id: str, new_props: Mapping[str, Any]) -> int:
    """Copy the current node to `@v<n>`, link it, then apply `new_props`. Returns the new version."""
    label = ids.label_of(node_id)
    rel = VERSION_RELS.get(label)
    if rel is None:
        raise ValueError(f"{label} has no version history")
    old = store.get_node(node_id)
    if old is None:
        raise NodeNotFound(node_id)
    n = int(old.get("version") or 1)

    copy = {k: v for k, v in old.items() if not k.startswith("_")}
    copy_id = f"{node_id}@v{n}"
    copy["id"] = copy_id
    copy["version"] = n
    store.upsert_nodes(label, [copy], partial=True)

    link = {"method": "structural", "confidence": 1.0, "version": n}
    if n > 1:
        # Re-point the chain: the old head moves behind the new copy.
        previous = f"{node_id}@v{n - 1}"
        store.delete_links(rel, label, label, [(node_id, previous)])
        store.upsert_links(
            rel, label, label, [LinkRow(copy_id, previous, link | {"version": n - 1})]
        )
    store.upsert_links(rel, label, label, [LinkRow(node_id, copy_id, link)])

    changes: dict[str, Any] = {"id": node_id, **new_props, "version": n + 1}
    if label == "SlackMessage":
        changes["edited"] = True
    if "editedAt" in store.ontology.node(label).properties:
        changes.setdefault("editedAt", to_graph_value(datetime.now(UTC)))
    store.update_nodes(label, [changes])
    return n + 1


def version_slack_message(store: GraphStore, msg_id: str, new_props: Mapping[str, Any]) -> int:
    """Record a Slack edit: old text goes to `@v<n>`, the main node gets the new text."""
    if ids.label_of(msg_id) != "SlackMessage":
        raise ValueError(f"not a Slack message id: {msg_id!r}")
    return version_node(store, msg_id, new_props)


def version_linear_issue(store: GraphStore, issue_id: str, new_props: Mapping[str, Any]) -> int:
    """Record an edit of a Linear issue (title, description)."""
    if ids.label_of(issue_id) != "LinearIssue":
        raise ValueError(f"not a Linear issue id: {issue_id!r}")
    return version_node(store, issue_id, new_props)


def version_linear_comment(store: GraphStore, comment_id: str, new_props: Mapping[str, Any]) -> int:
    """Record an edit of a Linear comment (body)."""
    if ids.label_of(comment_id) != "LinearComment":
        raise ValueError(f"not a Linear comment id: {comment_id!r}")
    return version_node(store, comment_id, new_props)
