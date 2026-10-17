"""Versioned source ingestion and bounded evidence investigation.

Ontology v1 is an explicit, curated mapping. Source text is untrusted evidence;
we never infer identity, approval authority, or executable commands from prose.
"""

from .contracts import Payload, Rejected, Sources, Store, digest

ONTOLOGY = "actron-ontology-v1"


class Ingestor:
    def __init__(self, store: Store) -> None:
        self.store = store

    def sync(self, source_id: str, source: Sources) -> Payload:
        with self.store.lock(f"ingest:{source_id}"):
            progress = self.store.get("Import", source_id) or {"id": source_id, "cursor": None}
            cursor = progress.get("cursor")
            # Completed imports intentionally restart: connectors expose current edits.
            if progress.get("complete"):
                cursor = None
            progress = {**progress, "complete": False}
            self.store.put("Import", source_id, progress)
            seen: set[str] = set()
            count = 0
            while True:
                page = source.fetch(cursor)
                for record in page.get("records", []):
                    self._record(record)
                    count += 1
                next_cursor = page.get("cursor")
                complete = bool(page.get("complete", next_cursor is None))
                progress = {
                    "id": source_id,
                    "cursor": next_cursor,
                    "complete": complete,
                    "gaps": page.get("gaps", []),
                    "records": count,
                    "ontology": ONTOLOGY,
                }
                self.store.put("Import", source_id, progress)
                if complete:
                    return progress
                if next_cursor is None or str(next_cursor) in seen or next_cursor == cursor:
                    raise Rejected("connector cursor did not advance")
                seen.add(str(next_cursor))
                cursor = next_cursor

    def _record(self, record: Payload) -> None:
        for field in ("id", "provider", "revision", "project", "content", "locator"):
            if field not in record:
                raise Rejected(f"source record missing {field}")
        stable = f"{record['provider']}:{record['id']}"
        revision = f"{stable}:{record['revision']}"
        previous = self.store.get("SourceRevision", revision)
        if previous and previous["content_hash"] != digest(record):
            raise Rejected("immutable source revision changed; supply a new revision")
        envelope = {
            **record,
            "id": revision,
            "record_id": record["id"],
            "source_id": stable,
            "content_hash": digest(record),
            "ontology": ONTOLOGY,
            "availability": record.get("availability", "available"),
        }
        self.store.put("SourceRevision", revision, envelope)
        current_source = self.store.get("Source", stable)
        # A replay of an already recorded historical page cannot roll back a head.
        if not previous or not current_source or current_source["current"] == revision:
            if current_source and current_source["current"] != revision:
                self.store.link(
                    "SourceRevision",
                    revision,
                    "REVISES",
                    "SourceRevision",
                    current_source["current"],
                    {"ontology": ONTOLOGY},
                )
            self.store.put(
                "Source",
                stable,
                {
                    "id": stable,
                    "current": revision,
                    "availability": envelope["availability"],
                    "project": record["project"],
                },
            )
        self.store.link(
            "Source", stable, "HAS_REVISION", "SourceRevision", revision, {"ontology": ONTOLOGY}
        )
        behavior = record.get("behavior")
        if behavior:
            self.store.put(
                "Behavior",
                f"{record['project']}:{behavior}",
                {"id": behavior, "project": record["project"]},
            )
            self.store.link(
                "SourceRevision",
                revision,
                "SUPPORTS_BEHAVIOR",
                "Behavior",
                f"{record['project']}:{behavior}",
                {"method": "explicit-id", "certainty": "curated", "source": revision},
            )
        for claim in record.get("claims", []):
            if not all(field in claim for field in ("id", "text", "behavior")):
                raise Rejected("claim requires explicit id, text, and behavior")
            approval = claim.get("approval") or {}
            approved = claim.get("status") == "approved" and all(
                approval.get(field) for field in ("actor", "source", "revision")
            )
            claim_key = f"{revision}:{claim['id']}"
            item = {
                **claim,
                "id": claim_key,
                "claim_id": claim["id"],
                "source": revision,
                "source_id": stable,
                "project": record["project"],
                "status": "approved" if approved else "proposal",
                "ontology": ONTOLOGY,
                "method": claim.get("method", "curated"),
                "certainty": claim.get("certainty", "explicit"),
            }
            self.store.put("Claim", claim_key, item)
            self.store.link(
                "Claim",
                claim_key,
                "SUPPORTED_BY",
                "SourceRevision",
                revision,
                {"method": item["method"], "certainty": item["certainty"], "ontology": ONTOLOGY},
            )
            behavior_key = f"{record['project']}:{claim['behavior']}"
            self.store.put(
                "Behavior", behavior_key, {"id": claim["behavior"], "project": record["project"]}
            )
            self.store.link(
                "Claim",
                claim_key,
                "APPLIES_TO",
                "Behavior",
                behavior_key,
                {"source": revision, "method": "explicit-id", "ontology": ONTOLOGY},
            )
            if approved:
                approval_key = f"{claim_key}:approval"
                self.store.put(
                    "HistoricalApproval",
                    approval_key,
                    {**approval, "id": approval_key, "historical_only": True, "source": revision},
                )
                self.store.link(
                    "HistoricalApproval",
                    approval_key,
                    "APPROVES",
                    "Claim",
                    claim_key,
                    {"source": revision, "ontology": ONTOLOGY},
                )
        snapshot = record.get("snapshot")
        if snapshot and envelope["availability"] == "available":
            if not snapshot.get("repo") or not snapshot.get("commit"):
                raise Rejected("code snapshot requires repo and commit")
            for item in snapshot.get("components", []) + snapshot.get("checks", []):
                if (
                    item.get("commit", snapshot["commit"]) != snapshot["commit"]
                    or item.get("repo", snapshot["repo"]) != snapshot["repo"]
                ):
                    raise Rejected("mixed repository snapshot metadata")
            snapshot_key = f"{snapshot['repo']}:{snapshot['commit']}"
            existing = self.store.get("Snapshot", snapshot_key)
            mapped = {
                **snapshot,
                "id": snapshot_key,
                "project": record["project"],
                "source": revision,
                "ontology": ONTOLOGY,
            }
            if existing and digest(existing) != digest(mapped):
                raise Rejected("snapshot changed for immutable commit")
            self.store.put("Snapshot", snapshot_key, mapped)
            repository = self.store.get("Repository", snapshot["repo"])
            if not existing or not repository or repository["current"] == snapshot_key:
                self.store.put(
                    "Repository",
                    snapshot["repo"],
                    {"id": snapshot["repo"], "current": snapshot_key},
                )
            self.store.link(
                "Snapshot",
                snapshot_key,
                "SUPPORTED_BY",
                "SourceRevision",
                revision,
                {"method": "git-snapshot", "commit": snapshot["commit"]},
            )
            for kind, field in (("Component", "components"), ("Check", "checks")):
                for item in snapshot.get(field, []):
                    key = f"{snapshot_key}:{item['id']}"
                    self.store.put(
                        kind, key, {**item, "snapshot": snapshot_key, "source": revision}
                    )
                    self.store.link(
                        "Snapshot",
                        snapshot_key,
                        "CONTAINS",
                        kind,
                        key,
                        {
                            "method": item.get("method", "curated"),
                            "commit": snapshot["commit"],
                            "source": revision,
                        },
                    )
                    for behavior_id in item.get("behaviors", []):
                        behavior_key = f"{record['project']}:{behavior_id}"
                        self.store.put(
                            "Behavior",
                            behavior_key,
                            {"id": behavior_id, "project": record["project"]},
                        )
                        self.store.link(
                            kind,
                            key,
                            "IMPLEMENTS" if kind == "Component" else "VERIFIES",
                            "Behavior",
                            behavior_key,
                            {
                                "source": revision,
                                "commit": snapshot["commit"],
                                "method": item.get("method", "curated"),
                            },
                        )
            for component in snapshot.get("components", []):
                for target in component.get("calls", []):
                    self.store.link(
                        "Component",
                        f"{snapshot_key}:{component['id']}",
                        "CALLS",
                        "Component",
                        f"{snapshot_key}:{target}",
                        {
                            "source": revision,
                            "commit": snapshot["commit"],
                            "method": component.get("method", "curated"),
                        },
                    )
            for check in snapshot.get("checks", []):
                for component_id in check.get("components", []):
                    self.store.link(
                        "Check",
                        f"{snapshot_key}:{check['id']}",
                        "VERIFIES",
                        "Component",
                        f"{snapshot_key}:{component_id}",
                        {
                            "source": revision,
                            "commit": snapshot["commit"],
                            "method": check.get("method", "curated"),
                        },
                    )


class Investigator:
    def __init__(self, store: Store) -> None:
        self.store = store

    def evidence(self, project: str, behavior: str, repo: str, base: str) -> Payload:
        gaps: list[str] = []
        repository = self.store.get("Repository", repo)
        snapshot = self.store.get("Snapshot", repository["current"]) if repository else None
        if not snapshot:
            gaps.append("Repository snapshot has not been ingested")
            snapshot = {"repo": repo, "commit": base, "components": [], "checks": []}
        elif snapshot["commit"] != base:
            gaps.append(f"Requested base {base} is stale; current snapshot is {snapshot['commit']}")
        if snapshot.get("project", project) != project:
            gaps.append("Repository snapshot belongs to another project")
        for item in snapshot.get("components", []) + snapshot.get("checks", []):
            if (
                item.get("commit", snapshot["commit"]) != snapshot["commit"]
                or item.get("repo", repo) != repo
            ):
                gaps.append("Mixed repository snapshot metadata requires re-import")
        components = [
            dict(
                item,
                commit=snapshot["commit"],
                locator=f"{repo}@{snapshot['commit']}:{item.get('path', item['id'])}",
            )
            for item in snapshot.get("components", [])
        ]
        # Bounded fixed-point over curated/extracted static call edges only.
        selected = {item["id"] for item in components if behavior in item.get("behaviors", [])}
        for _ in range(8):
            reached = {item["id"] for item in components if set(item.get("calls", [])) & selected}
            reached |= {
                target
                for item in components
                if item["id"] in selected
                for target in item.get("calls", [])
            }
            if reached <= selected:
                break
            selected |= reached
        else:
            gaps.append("Dependency traversal reached depth bound (8)")
        affected = [item for item in components if item["id"] in selected]
        behaviors = {behavior} | {b for item in affected for b in item.get("behaviors", [])}
        checks = [
            dict(
                item,
                commit=snapshot["commit"],
                locator=f"{repo}@{snapshot['commit']}:{item.get('path', item['id'])}",
            )
            for item in snapshot.get("checks", [])
            if behaviors & set(item.get("behaviors", []))
            or selected & set(item.get("components", []))
        ]
        claims = [
            item
            for item in self.store.list("Claim")
            if item["project"] == project and item["behavior"] in behaviors
        ]
        available: list[Payload] = []
        source_ids: set[str] = set()
        for claim in claims:
            source = self.store.get("Source", claim["source_id"])
            source_ids.add(claim["source"])
            if source and source["availability"] == "available":
                available.append(claim)
            else:
                gaps.append(
                    f"Source unavailable: {claim['source_id']}; historical content is unverified"
                )
        approved = [claim for claim in available if claim["status"] == "approved"]
        superseded = {
            old
            for replacement in approved
            for old in replacement.get("supersedes", [])
            for claim in approved
            if old in (claim["claim_id"], claim["id"])
            and replacement["behavior"] == claim["behavior"]
        }
        outcomes = [
            outcome
            for outcome in self.store.list("Outcome")
            if outcome.get("merged")
            and outcome.get("project") == project
            and outcome.get("behavior") in behaviors
        ]
        superseded_outcomes = {
            previous["id"]
            for replacement in outcomes
            for previous in outcomes
            if previous["behavior"] == replacement["behavior"]
            and previous["id"] in replacement.get("supersedes", [])
        }
        for outcome in outcomes:
            for claim in approved:
                if claim["behavior"] == outcome["behavior"]:
                    superseded.update(
                        old
                        for old in outcome.get("supersedes", [])
                        if old in (claim["id"], claim["claim_id"])
                    )
        current = [
            claim
            for claim in approved
            if claim["claim_id"] not in superseded and claim["id"] not in superseded
        ]
        # Multiple immutable revisions of an unchanged claim are one scoped rule.
        unique: dict[str, Payload] = {}
        for claim in current:
            source = self.store.get("Source", claim["source_id"])
            if claim["claim_id"] not in unique or (source and source["current"] == claim["source"]):
                unique[claim["claim_id"]] = claim
        decisions = list(unique.values())
        current_outcomes = [
            outcome for outcome in outcomes if outcome["id"] not in superseded_outcomes
        ]
        for outcome in current_outcomes:
            decisions.append(
                {
                    "id": outcome["id"],
                    "claim_id": outcome["id"],
                    "behavior": outcome["behavior"],
                    "text": outcome.get(
                        "decision",
                        outcome.get("scope", {}).get("objective", "Merged scoped change"),
                    ),
                    "status": "approved",
                    "source": outcome.get("pr", ""),
                    "approval": {
                        "request": outcome.get("request"),
                        "revision": outcome.get("revision"),
                        "head": outcome.get("head"),
                    },
                    "method": "confirmed-merge",
                    "certainty": "explicit",
                    "scope": outcome.get("scope", {}),
                }
            )
        proposals = [claim for claim in available if claim["status"] != "approved"]
        decision_ids = {claim["claim_id"] for claim in decisions} | {
            claim["id"] for claim in decisions
        }
        conflict = any(decision_ids & set(claim.get("conflicts_with", [])) for claim in decisions)
        if conflict:
            gaps.append("Conflicting approved decisions require clarification")
        if not any(claim["behavior"] == behavior for claim in decisions):
            gaps.append(f"No available approved decision for {behavior}")
        for progress in self.store.list("Import"):
            if not progress.get("complete"):
                gaps.append(f"Partial import: {progress['id']}")
            gaps.extend(progress.get("gaps", []))
        gaps.extend(snapshot.get("gaps", []))
        gaps.append(
            "Dependency coverage is bounded; dynamic calls and ambiguous identities remain unresolved"
        )
        if snapshot.get("source"):
            source_ids.add(snapshot["source"])
        source_ids.update(
            source["id"]
            for source in self.store.list("SourceRevision")
            if source.get("repo") == repo
            and source.get("commit") == snapshot["commit"]
            and source.get("path") in {item.get("path") for item in affected + checks}
        )
        sources = [
            source
            for key in sorted(source_ids)
            if (source := self.store.get("SourceRevision", key))
        ]
        # Preserve historical content while marking its current verification status.
        for source in sources:
            head = self.store.get("Source", source["source_id"])
            source["current_availability"] = (
                head.get("availability", "unknown") if head else "unknown"
            )
            source["is_current_revision"] = bool(head and head.get("current") == source["id"])
            if source["current_availability"] != "available":
                gaps.append(
                    f"Source unavailable: {source['source_id']}; historical content is unverified"
                )
        constraints = [claim["text"] for claim in decisions]
        superseded_text = {
            claim["text"]
            for claim in approved
            if claim["claim_id"] in superseded or claim["id"] in superseded
        }
        superseded_text.update(
            outcome.get("decision", outcome.get("scope", {}).get("objective", ""))
            for outcome in outcomes
            if outcome["id"] in superseded_outcomes
        )
        constraints.extend(
            constraint
            for outcome in current_outcomes
            for constraint in outcome.get("scope", {}).get("constraints", [])
            if constraint not in superseded_text
        )
        result: Payload = {
            "project": project,
            "behavior": behavior,
            "decisions": decisions,
            "historical": [
                claim
                for claim in approved
                if claim["claim_id"] in superseded or claim["id"] in superseded
            ]
            + [outcome for outcome in outcomes if outcome["id"] in superseded_outcomes],
            "proposals": proposals,
            "constraints": list(dict.fromkeys(constraints)),
            "sources": sources,
            "components": affected,
            "checks": checks,
            "gaps": list(dict.fromkeys(gaps)),
            "snapshot": {"repo": repo, "commit": snapshot["commit"]},
            "conflict": conflict,
            "ontology": ONTOLOGY,
        }
        result["paths"] = [
            {
                "claim": claim["id"],
                "relation": "SUPPORTED_BY",
                "source": claim["source"],
                "behavior": claim["behavior"],
            }
            for claim in decisions
        ]
        result["graph_paths"] = result["paths"]
        result["critical_gaps"] = [
            gap
            for gap in result["gaps"]
            if gap.startswith(
                (
                    "Repository snapshot",
                    "Requested base",
                    "Partial import",
                    "Source unavailable",
                    "No available approved decision",
                    "Conflicting approved decisions",
                    "Mixed repository snapshot",
                )
            )
        ]
        result["fingerprint"] = digest(result)
        return result
