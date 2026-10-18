"""Identity (spec A, A12.1): Slack, GitHub, Linear and git accounts -> one `Person` through `Identity`.

Match order: (1) exact lowercased email across sources (GitHub noreply emails map to the GitHub user);
(2) `config/identity_map.yaml`; nothing else, never display names. Accounts with no match get their own
`Person` with `matchMethod = unresolved`. When a later email or mapping joins two people, the links of the
extra `Person` move to the kept one and the extra node is deleted.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from actron.config import REPO_ROOT
from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow
from actron.logging import get_logger

log = get_logger(__name__)

IDENTITY_MAP = REPO_ROOT / "config" / "identity_map.yaml"
NOREPLY = re.compile(r"^(?:(\d+)\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com$")

# account label -> (provider, link from Identity)
PROVIDERS: dict[str, tuple[str, str]] = {
    "SlackUser": ("slack", "IS_SLACK_USER"),
    "GithubUser": ("github", "IS_GITHUB_USER"),
    "LinearUser": ("linear", "IS_LINEAR_USER"),
    "GitAuthor": ("git", "IS_GIT_AUTHOR"),
}
ID_PREFIX = {
    "SlackUser": "slack:user:",
    "GithubUser": "github:user:",
    "LinearUser": "linear:user:",
    "GitAuthor": "git:author:",
}
NAME_PRIORITY = ("linear", "slack", "github", "git")


@dataclass
class Account:
    label: str
    node_id: str
    provider: str
    account_id: str
    email: str | None
    handle: str | None
    name: str | None
    avatar: str | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.account_id}"


@dataclass
class IdentityReport:
    accounts: int = 0
    people: int = 0
    resolved_people: int = 0
    unresolved: list[str] = field(default_factory=list)
    merged: int = 0
    unmatched_mapping_entries: list[str] = field(default_factory=list)


def load_identity_map(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or IDENTITY_MAP
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of {{person, accounts}} entries")
    out = []
    for entry in data:
        if isinstance(entry, dict) and isinstance(entry.get("accounts"), list):
            out.append(
                {
                    "person": str(entry.get("person") or ""),
                    "accounts": [str(a) for a in entry["accounts"]],
                }
            )
    return out


def _accounts(store: GraphStore) -> list[Account]:
    out: list[Account] = []
    queries = {
        "SlackUser": "MATCH (u:SlackUser) WHERE coalesce(u.isBot, false) = false RETURN u.id AS id, u.email AS email, "
        "coalesce(u.displayName, u.name) AS handle, coalesce(u.realName, u.name) AS name, u.avatarUrl AS avatar",
        "GithubUser": "MATCH (u:GithubUser) RETURN u.id AS id, u.email AS email, u.login AS handle, "
        "coalesce(u.name, u.login) AS name, u.avatarUrl AS avatar",
        "LinearUser": "MATCH (u:LinearUser) RETURN u.id AS id, u.email AS email, u.displayName AS handle, "
        "coalesce(u.name, u.displayName) AS name, u.avatarUrl AS avatar",
        "GitAuthor": "MATCH (u:GitAuthor) RETURN u.id AS id, u.email AS email, u.email AS handle, u.name AS name, "
        "null AS avatar",
    }
    for label, cypher in queries.items():
        provider = PROVIDERS[label][0]
        prefix = ID_PREFIX[label]
        for r in store.query(cypher, read_only=True):
            nid = str(r["id"])
            email = str(r["email"]).strip().lower() if r.get("email") else None
            out.append(
                Account(
                    label,
                    nid,
                    provider,
                    nid.removeprefix(prefix),
                    email,
                    str(r["handle"]) if r.get("handle") else None,
                    str(r["name"]) if r.get("name") else None,
                    str(r["avatar"]) if r.get("avatar") else None,
                )
            )
    return out


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.how: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str, how: str) -> None:
        ra, rb = self.find(a), self.find(b)
        for k in (a, b):
            if self.how.get(k) != "mapping_file":
                self.how[k] = how
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _mapping_lookup(accounts: list[Account]) -> dict[str, str]:
    """Mapping-file reference (`slack:U1`, `github:login`, `linear:<uuid>`, `git:email`) -> account key."""
    out: dict[str, str] = {}
    for a in accounts:
        out[a.key.lower()] = a.key
        if a.provider == "github" and a.handle:
            out[f"github:{a.handle.lower()}"] = a.key
        if a.provider == "git" and a.email:
            out[f"git:{a.email}"] = a.key
    return out


def group_accounts(
    accounts: list[Account], mapping: list[dict[str, Any]], report: IdentityReport | None = None
) -> tuple[dict[str, list[Account]], dict[str, str], dict[str, str]]:
    """Union accounts by email, noreply and mapping. Returns (groups by root, how per key, mapped names)."""
    uf = _Union()
    for a in accounts:
        uf.find(a.key)
    by_email: dict[str, list[Account]] = defaultdict(list)
    github_by_id = {a.account_id: a for a in accounts if a.provider == "github"}
    github_by_login = {a.handle.lower(): a for a in accounts if a.provider == "github" and a.handle}
    for a in accounts:
        if not a.email:
            continue
        m = NOREPLY.match(a.email)
        if m:
            gh = github_by_id.get(m.group(1) or "") or github_by_login.get(m.group(2).lower())
            if gh:
                uf.union(a.key, gh.key, "email")
            continue
        by_email[a.email].append(a)
    for group in by_email.values():
        for other in group[1:]:
            uf.union(group[0].key, other.key, "email")
    lookup = _mapping_lookup(accounts)
    names: dict[str, str] = {}
    for entry in mapping:
        keys = []
        for ref in entry["accounts"]:
            key = lookup.get(ref.strip().lower())
            if key:
                keys.append(key)
            elif report is not None:
                report.unmatched_mapping_entries.append(ref)
        for k in keys[1:]:
            uf.union(keys[0], k, "mapping_file")
        for k in keys:
            uf.how[k] = "mapping_file" if len(keys) > 1 else uf.how.get(k, "")
            if entry["person"]:
                names[k] = entry["person"]
    groups: dict[str, list[Account]] = defaultdict(list)
    for a in accounts:
        groups[uf.find(a.key)].append(a)
    return groups, uf.how, names


def _display_name(group: list[Account], names: dict[str, str]) -> str:
    for a in group:
        if a.key in names:
            return names[a.key]
    for provider in NAME_PRIORITY:
        for a in group:
            if a.provider == provider and a.name:
                return a.name
    return group[0].handle or group[0].account_id


def link_identities(
    store: GraphStore, ws: str, *, mapping_path: Path | None = None
) -> IdentityReport:
    """Recompute people and identities for the workspace (idempotent; A12.1, A-AC-70)."""
    report = IdentityReport()
    accounts = _accounts(store)
    report.accounts = len(accounts)
    groups, how, names = group_accounts(accounts, load_identity_map(mapping_path), report)
    existing = {
        str(r["identity"]): str(r["person"])
        for r in store.query(
            "MATCH (p:Person)-[:HAS_IDENTITY]->(i:Identity) RETURN p.id AS person, i.id AS identity",
            read_only=True,
        )
    }
    keep_people: set[str] = set()
    for group in groups.values():
        group.sort(key=lambda a: a.key)
        person_id = ids.person(ws, group[0].key)
        keep_people.add(person_id)
        resolved = len(group) > 1
        emails = sorted({a.email for a in group if a.email and not NOREPLY.match(a.email)})
        store.upsert_nodes(
            "Person",
            [
                {
                    "id": person_id,
                    "displayName": _display_name(group, names),
                    "primaryEmail": emails[0] if emails else None,
                    "emails": emails or None,
                    "avatarUrl": next((a.avatar for a in group if a.avatar), None),
                }
            ],
        )
        report.people += 1
        if resolved:
            report.resolved_people += 1
        for a in group:
            method = (how.get(a.key) or "email") if resolved else "unresolved"
            if not resolved and how.get(a.key) == "mapping_file":
                method = "mapping_file"
            iid = ids.identity(a.provider, a.account_id)
            store.upsert_nodes(
                "Identity",
                [
                    {
                        "id": iid,
                        "provider": a.provider,
                        "accountId": a.account_id,
                        "handle": a.handle,
                        "email": a.email,
                        "matchMethod": method,
                        "matchConfidence": 0.0 if method == "unresolved" else 1.0,
                    }
                ],
            )
            conf = 0.0 if method == "unresolved" else 1.0
            store.upsert_links(
                "HAS_IDENTITY",
                "Person",
                "Identity",
                [LinkRow(person_id, iid, {"method": "structural", "confidence": conf})],
            )
            store.upsert_links(
                PROVIDERS[a.label][1],
                "Identity",
                a.label,
                [LinkRow(iid, a.node_id, {"method": "structural", "confidence": 1.0})],
            )
            old = existing.get(iid)
            if old and old != person_id:
                store.query(
                    "MATCH (p:Person {id: $p})-[r:HAS_IDENTITY]->(i:Identity {id: $i}) DELETE r",
                    {"p": old, "i": iid},
                )
            if method == "unresolved":
                report.unresolved.append(a.node_id)
    for old in sorted(set(existing.values()) - keep_people):
        target = _merge_target(store, old, existing)
        if target:
            move_person_links(store, old, target)
            report.merged += 1
    return report


def _merge_target(store: GraphStore, old: str, existing: dict[str, str]) -> str | None:
    identities = [i for i, p in existing.items() if p == old]
    rows = store.query(
        "UNWIND $ids AS iid MATCH (p:Person)-[:HAS_IDENTITY]->(i:Identity {id: iid}) "
        "WHERE p.id <> $old RETURN p.id AS id LIMIT 1",
        {"ids": identities, "old": old},
        read_only=True,
    )
    return str(rows[0]["id"]) if rows else None


def move_person_links(store: GraphStore, old: str, new: str) -> int:
    """Move every link of Person `old` to Person `new`, then delete `old` (A12.1 merge)."""
    moved = 0
    onto = store.ontology
    for rel, frm, to in onto.relationships:
        if frm == "Person" and to != "Identity":
            rows = store.query(
                f"MATCH (a:Person {{id: $id}})-[r:`{rel}`]->(b:`{to}`) RETURN b.id AS b, "
                "properties(r) AS p",
                {"id": old},
                read_only=True,
            )
            if rows:
                moved += store.upsert_links(
                    rel, "Person", to, [LinkRow(new, str(r["b"]), _props(r["p"])) for r in rows]
                ).created
        if to == "Person":
            rows = store.query(
                f"MATCH (a:`{frm}`)-[r:`{rel}`]->(b:Person {{id: $id}}) RETURN a.id AS a, "
                "properties(r) AS p",
                {"id": old},
                read_only=True,
            )
            if rows:
                moved += store.upsert_links(
                    rel, frm, "Person", [LinkRow(str(r["a"]), new, _props(r["p"])) for r in rows]
                ).created
    store.query("MATCH (p:Person {id: $id}) DETACH DELETE p", {"id": old})
    log.info("merged people", extra={"from": old, "to": new, "links": moved})
    return moved


def _props(raw: Any) -> dict[str, Any]:
    props = dict(raw or {})
    props.setdefault("method", "structural")
    props.setdefault("confidence", 1.0)
    return props
