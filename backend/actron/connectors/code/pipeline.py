"""Code and git ingestion for one repository into a workspace graph (spec A, A6, A7, A11 code steps).

`ingest_code` runs a full backfill when no cursor is given and an incremental run from `since_sha` otherwise.
Both modes walk the whole snapshot (needed for resolution) but write only what changed in incremental mode:
files whose content hash differs, their symbols (only when the body hash or line range changed), chunks,
sections and outgoing links; deleted files and symbols are tombstoned; renames get RENAMED_TO links.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from actron.connectors.code import codeowners as owners_mod
from actron.connectors.code.chunks import plan_chunks
from actron.connectors.code.clone import CloneInfo, clone_dir_for, clone_or_fetch
from actron.connectors.code.docs import MentionIndex, find_mentions, split_document
from actron.connectors.code.git_history import (
    analyze_history,
    usable_renames,
    write_blame,
    write_history,
    write_refs,
)
from actron.connectors.code.git_log import CommitRecord, head_sha, is_ancestor, read_log
from actron.connectors.code.hunks import read_patches
from actron.connectors.code.incremental import (
    GraphState,
    load_state,
    replace_out_links,
    repoint_callers,
    write_renames,
)
from actron.connectors.code.languages import language_for
from actron.connectors.code.manifests import (
    Component,
    Dependency,
    component_for,
    find_components,
    internal_dependencies,
    internal_names,
    normalize,
    package_for_import,
)
from actron.connectors.code.metrics import compute_metrics
from actron.connectors.code.model import ParsedFile, split_lines
from actron.connectors.code.parse import parse_file
from actron.connectors.code.resolve import (
    Resolution,
    Snapshot,
    build_snapshot,
    resolve_snapshot,
    symbol_id,
)
from actron.connectors.code.tests_link import TestLinks, link_tests, mark_tests
from actron.connectors.code.walk import FileEntry, walk
from actron.graph import ids
from actron.graph.store import GraphStore, LinkRow
from actron.logging import get_logger

log = get_logger(__name__)

CODE_LABELS = ("CodeRepository", "CodeComponent", "CodeDependency", "CodeFile", "CodeClass", "CodeFunction",
               "CodeChunk", "CodeDocument", "CodeOwnerRule", "GitCommit", "GitAuthor", "GitBranch", "GitTag",
               "GitFileChange")
CODE_RELS = ("COMPONENT_IN_REPO", "FILE_IN_REPO", "FILE_IN_COMPONENT", "COMPONENT_DEPENDS_ON", "USES_PACKAGE",
             "CLASS_DEFINED_IN", "FUNCTION_DEFINED_IN", "METHOD_OF", "NESTED_IN", "INHERITS_FROM", "CHUNK_OF",
             "SECTION_OF", "SUBSECTION_OF", "IMPORTS", "IMPORTS_PACKAGE", "CALLS", "INSTANTIATES", "TESTS",
             "TESTS_CLASS", "TEST_FILE_FOR", "DOC_MENTIONS_FILE", "DOC_MENTIONS_FUNCTION", "DOC_MENTIONS_CLASS",
             "MATCHES_OWNER_RULE", "HEAD_COMMIT", "COMMIT_IN_REPO", "HAS_PARENT", "AUTHORED_BY", "HAS_FILE_CHANGE",
             "CHANGE_OF_FILE", "TOUCHED", "TOUCHED_CLASS", "BLAME_OWNS", "BLAME_OWNS_FILE", "GIT_BRANCH_IN_REPO",
             "BRANCH_HEAD", "RENAMED_TO", "CLASS_RENAMED_TO", "FILE_RENAMED_TO", "TAGS_COMMIT")
STRUCT = {"method": "structural", "confidence": 1.0}


class EventSink(Protocol):
    def __call__(self, type: str, payload: dict[str, Any], *, actor: str = "actron",
                 surface: str = "system") -> Awaitable[None]: ...


@dataclass
class CodeIngestReport:
    ws: str
    repo: str
    mode: str  # backfill or incremental
    head_sha: str
    previous_sha: str | None
    branch: str
    counts: dict[str, int] = field(default_factory=dict)  # nodes per label in the graph after the run
    links: dict[str, int] = field(default_factory=dict)  # relationships per type after the run
    written: dict[str, int] = field(default_factory=dict)  # nodes written (upserted) per label in this run
    unresolved_calls: int = 0
    files_changed: int = 0
    files_deleted: int = 0
    commits: int = 0
    renames: int = 0
    pagerank_method: str = ""
    partial_reason: str | None = None
    duration_ms: int = 0
    timings: dict[str, float] = field(default_factory=dict)
    resolution_tiers: dict[str, int] = field(default_factory=dict)


ProgressFn = Callable[[str, dict[str, int]], None]


def _now() -> datetime:
    return datetime.now(UTC)


class CodeIngestion:
    """One run. Steps are plain methods so a workflow can call them one by one; `run()` calls them all."""

    STEPS = ("walk_and_parse", "resolve", "link_tests", "git_log", "write_snapshot", "documents", "manifests",
             "codeowners", "hunks", "blame", "metrics")

    def __init__(self, store: GraphStore, repo: str, repo_dir: Path, *, branch: str, url: str,
                 depth: int = 2000, since_sha: str | None = None, progress: ProgressFn | None = None,
                 blame: bool = True) -> None:
        self.store = store
        self.repo = repo.lower()
        self.repo_dir = repo_dir
        self.branch = branch
        self.url = url
        self.depth = depth
        self.since_sha = since_sha
        self.progress = progress
        self.do_blame = blame
        self.report = CodeIngestReport(ws=store.workspace_id, repo=self.repo,
                                       mode="incremental" if since_sha else "backfill", head_sha="",
                                       previous_sha=since_sha, branch=branch)
        self.entries: dict[str, FileEntry] = {}
        self.parsed: dict[str, ParsedFile] = {}
        self.snap: Snapshot | None = None
        self.res: Resolution | None = None
        self.links: TestLinks | None = None
        self.test_files: set[str] = set()
        self.state = GraphState()
        self.scope: set[str] = set()  # paths whose nodes and outgoing links are (re)written
        self.deleted_paths: set[str] = set()
        self.commits: list[CommitRecord] = []
        self.history_since: str | None = since_sha
        self.written: Counter[str] = Counter()

    # helpers
    def _emit(self, phase: str, counts: dict[str, int]) -> None:
        if self.progress:
            self.progress(phase, counts)

    def _timed(self, name: str, fn: Callable[[], None]) -> None:
        t0 = time.perf_counter()
        fn()
        self.report.timings[name] = round(time.perf_counter() - t0, 2)
        log.info("code ingestion step", extra={"step": name, "seconds": self.report.timings[name]})

    def _upsert(self, label: str, rows: list[dict[str, Any]]) -> None:
        if rows:
            self.written[label] += self.store.upsert_nodes(label, rows)

    def file_id(self, path: str) -> str:
        return ids.code_file(self.repo, path)

    # steps
    def walk_and_parse(self) -> None:
        self.report.head_sha = head_sha(self.repo_dir)
        self.entries = {e.path: e for e in walk(self.repo_dir)}
        for path, entry in self.entries.items():
            if entry.stored and language_for(path).tier in (1, 2):
                pf = parse_file(path, entry.data)
                if pf is not None:
                    self.parsed[path] = pf
        self.test_files = mark_tests(self.parsed)
        self.state = load_state(self.store, self.repo)
        incremental = self.since_sha is not None and not self.state.empty
        current_ids = {self.file_id(p): p for p in self.entries}
        if incremental:
            for path, entry in self.entries.items():
                row = self.state.files.get(self.file_id(path))
                if row is None or row.get("deleted") or row.get("contentHash") != entry.content_hash:
                    self.scope.add(path)
        else:
            self.scope = set(self.entries)
        for fid, row in self.state.files.items():
            if fid not in current_ids and not row.get("deleted"):
                self.deleted_paths.add(str(row.get("path") or ids.parse_id(fid).parts["path"]))
        self.report.files_changed = len(self.scope)
        self.report.files_deleted = len(self.deleted_paths)
        self._emit("walk", {"files": len(self.entries), "changed": len(self.scope)})

    def resolve(self) -> None:
        sources = {p: e.data for p, e in self.entries.items()
                   if e.stored and (p.endswith(".json") or PurePosixPath(p).name == "go.mod")}
        sources.update({p: b"" for p in self.entries if p not in sources})
        self.snap = build_snapshot(self.repo, sources, parsed=self.parsed)
        self.res = resolve_snapshot(self.snap)
        self.report.unresolved_calls = self.res.unresolved_total
        self.report.resolution_tiers = dict(self.res.tiers)

    def link_tests(self) -> None:
        assert self.snap is not None and self.res is not None
        self.links = link_tests(self.snap, self.res, self.test_files)

    def git_log(self) -> None:
        since = self.since_sha if not self.state.empty else None
        if since and not is_ancestor(self.repo_dir, since):
            self.report.partial_reason = "history rewritten"
            since = None
        self.history_since = since
        self.commits = list(read_log(self.repo_dir, since, self.depth))
        self.report.commits = len(self.commits)
        self._emit("git_log", {"commits": len(self.commits)})

    def hunks(self) -> None:
        patches = read_patches(self.repo_dir, self.history_since, self.depth) if self.commits else {}
        self.analysis = analyze_history(self.repo, self.repo_dir, self.commits, patches)

    # writing
    def _symbol_rows(self, path: str, pf: ParsedFile) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        assert self.res is not None
        fns: list[dict[str, Any]] = []
        classes: list[dict[str, Any]] = []
        last = getattr(self, "analysis", None)
        for sym in pf.symbols:
            sid = symbol_id(self.repo, path, sym)
            base: dict[str, Any] = {
                "id": sid, "name": sym.name, "qualifiedName": sym.qualname, "startLine": sym.start_line,
                "endLine": sym.end_line, "body": sym.body, "docstring": sym.docstring,
                "decorators": sym.decorators, "isTest": sym.is_test, "contentHash": sym.content_hash,
                "deleted": False,
            }
            if sym.kind == "class":
                classes.append({**base, "bases": sym.bases})
                continue
            row = {**base, "kind": sym.fn_kind, "signature": sym.signature, "parameters": sym.parameters,
                   "returnType": sym.return_type, "isAsync": sym.is_async, "isPublic": sym.is_public,
                   "loc": sym.loc, "unresolvedCalls": self.res.unresolved.get(sid, 0)}
            if last is not None and sid in last.last_touch:
                sha, when = last.last_touch[sid]
                row["lastCommitSha"] = sha
                row["lastChangedAt"] = datetime.fromisoformat(when)
            fns.append(row)
        return fns, classes

    def _changed(self, row: dict[str, Any], existing: dict[str, dict[str, Any]]) -> bool:
        old = existing.get(row["id"])
        if old is None or old.get("deleted"):
            return True
        return (old.get("contentHash") != row["contentHash"] or old.get("startLine") != row["startLine"]
                or old.get("endLine") != row["endLine"] or self.since_sha is None)

    def write_snapshot(self) -> None:
        assert self.snap is not None and self.res is not None and self.links is not None
        store, repo = self.store, self.repo
        repo_id = ids.code_repo(repo)
        langs = Counter(e.language for e in self.entries.values() if e.tier in (1, 2))
        self._upsert("CodeRepository", [{
            "id": repo_id, "name": repo, "url": self.url, "defaultBranch": self.branch,
            "headSha": self.report.head_sha, "languages": [lang for lang, _ in langs.most_common()],
            "fileCount": len(self.entries), "unresolvedCallCount": self.res.unresolved_total, "syncedAt": _now(),
        }])
        # files
        file_rows: list[dict[str, Any]] = []
        last_file = getattr(self, "analysis", None)
        for path in sorted(self.scope):
            e = self.entries[path]
            row: dict[str, Any] = {
                "id": self.file_id(path), "path": path, "language": e.language, "size": e.size,
                "contentHash": e.content_hash, "isTest": path in self.test_files, "isSkipped": e.is_skipped,
                "skipReason": e.skip_reason, "deleted": False,
                "loc": len(split_lines(e.text)) if e.text is not None else None, "text": e.text,
            }
            if last_file is not None and path in last_file.last_file_change:
                row["lastCommitSha"] = last_file.last_file_change[path][0]
            file_rows.append(row)
        self._upsert("CodeFile", file_rows)
        store.upsert_links("FILE_IN_REPO", "CodeFile", "CodeRepository",
                           [LinkRow(r["id"], repo_id, STRUCT) for r in file_rows])
        # symbols
        fn_rows: list[dict[str, Any]] = []
        cls_rows: list[dict[str, Any]] = []
        scope_fn_ids: list[str] = []
        scope_cls_ids: list[str] = []
        new_ids: set[str] = set()
        for path in sorted(self.scope):
            pf = self.parsed.get(path)
            if pf is None:
                continue
            fns, classes = self._symbol_rows(path, pf)
            scope_fn_ids += [r["id"] for r in fns]
            scope_cls_ids += [r["id"] for r in classes]
            new_ids.update(r["id"] for r in fns + classes)
            fn_rows += [r for r in fns if self._changed(r, self.state.functions)]
            cls_rows += [r for r in classes if self._changed(r, self.state.classes)]
        # unresolvedCalls can change without a body change: include those rows too
        self._upsert("CodeClass", cls_rows)
        self._upsert("CodeFunction", fn_rows)
        written_ids = {r["id"] for r in fn_rows + cls_rows}
        structural_fn: list[LinkRow] = []
        structural_cls: list[LinkRow] = []
        method_of: list[LinkRow] = []
        nested_in: list[LinkRow] = []
        for path in sorted(self.scope):
            pf = self.parsed.get(path)
            if pf is None:
                continue
            keyed = self.snap.by_file.get(path, {})
            for sym in pf.symbols:
                sid = symbol_id(repo, path, sym)
                if sid not in written_ids:
                    continue
                if sym.kind == "class":
                    structural_cls.append(LinkRow(sid, self.file_id(path), STRUCT))
                else:
                    structural_fn.append(LinkRow(sid, self.file_id(path), STRUCT))
                parent = keyed.get(sym.parent) if sym.parent else None
                if parent is None and sym.parent_obj is not None:
                    parent = self.snap.refs.get(symbol_id(repo, path, sym.parent_obj))
                if parent is not None and sym.kind == "function":
                    if parent.sym.kind == "class":
                        method_of.append(LinkRow(sid, parent.id, STRUCT))
                    else:
                        nested_in.append(LinkRow(sid, parent.id, STRUCT))
        store.upsert_links("FUNCTION_DEFINED_IN", "CodeFunction", "CodeFile", structural_fn)
        store.upsert_links("CLASS_DEFINED_IN", "CodeClass", "CodeFile", structural_cls)
        store.upsert_links("METHOD_OF", "CodeFunction", "CodeClass", method_of)
        store.upsert_links("NESTED_IN", "CodeFunction", "CodeFunction", nested_in)
        # unresolved counts for functions whose body did not change
        stale_counts = [{"id": sid, "unresolvedCalls": self.res.unresolved.get(sid, 0)}
                        for sid in scope_fn_ids if sid not in written_ids
                        and self.state.functions.get(sid, {}).get("unresolvedCalls") is not None]
        if stale_counts:
            store.update_nodes("CodeFunction", stale_counts)
        # tombstones: symbols gone from scope files, and everything in deleted files
        now = _now()
        scope_prefixes = {path for path in self.scope} | self.deleted_paths
        gone_fn = [i for i, r in self.state.functions.items() if not r.get("deleted") and i not in new_ids
                   and ids.parse_id(i).parts["path"] in scope_prefixes]
        gone_cls = [i for i, r in self.state.classes.items() if not r.get("deleted") and i not in new_ids
                    and ids.parse_id(i).parts["path"] in scope_prefixes]
        if gone_fn:
            store.tombstone("CodeFunction", gone_fn, now)
        if gone_cls:
            store.tombstone("CodeClass", gone_cls, now)
        if self.deleted_paths:
            store.tombstone("CodeFile", [self.file_id(p) for p in self.deleted_paths], now)
        self.gone_fn = gone_fn
        self.written["tombstoned"] += len(gone_fn) + len(gone_cls) + len(self.deleted_paths)
        # chunks
        chunk_rows: list[dict[str, Any]] = []
        chunk_links: list[LinkRow] = []
        keep_chunks: set[str] = set()
        for path in sorted(self.scope):
            e = self.entries[path]
            if not e.stored or e.text is None:
                continue
            for c in plan_chunks(path, e.text, self.parsed.get(path)):
                cid = ids.code_chunk(repo, path, c.start, c.end)
                keep_chunks.add(cid)
                chunk_rows.append({"id": cid, "startLine": c.start, "endLine": c.end, "text": c.text,
                                   "kind": c.kind, "deleted": False})
                chunk_links.append(LinkRow(cid, self.file_id(path), STRUCT))
        self._upsert("CodeChunk", chunk_rows)
        store.upsert_links("CHUNK_OF", "CodeChunk", "CodeFile", chunk_links)
        stale_chunks = [i for i, r in self.state.chunks.items() if not r.get("deleted") and i not in keep_chunks
                        and ids.parse_id(i).parts["path"] in scope_prefixes]
        if stale_chunks:
            store.tombstone("CodeChunk", stale_chunks, now)
        # calls, instantiations, inheritance, tests, imports from scope files (and deleted functions)
        callers = scope_fn_ids + gone_fn
        scope_set = set(scope_fn_ids)

        def calls_rows() -> list[LinkRow]:
            assert self.res is not None
            out = []
            for (a, b), e in self.res.calls.items():
                if a in scope_set:
                    out.append(LinkRow(a, b, {"method": "structural" if e.resolution in ("local", "import")
                                              else "inferred", "confidence": e.confidence,
                                              "resolution": e.resolution, "callSiteLines": sorted(e.lines),
                                              "count": e.count}))
            return out

        replace_out_links(store, "CALLS", "CodeFunction", "CodeFunction", callers, calls_rows())
        inst = [LinkRow(a, b, {"method": "structural" if e.resolution in ("local", "import") else "inferred",
                               "confidence": e.confidence, "callSiteLines": sorted(e.lines)})
                for (a, b), e in self.res.instantiates.items() if a in scope_set]
        replace_out_links(store, "INSTANTIATES", "CodeFunction", "CodeClass", callers, inst)
        tests = [LinkRow(a, b, {"method": m, "confidence": c}) for (a, b), (m, c) in self.links.tests.items()
                 if a in scope_set]
        replace_out_links(store, "TESTS", "CodeFunction", "CodeFunction", callers, tests)
        tests_cls = [LinkRow(a, b, {"method": m, "confidence": c})
                     for (a, b), (m, c) in self.links.tests_class.items() if a in scope_set]
        replace_out_links(store, "TESTS_CLASS", "CodeFunction", "CodeClass", callers, tests_cls)
        cls_scope = set(scope_cls_ids)
        inh = [LinkRow(a, b, {"method": "structural", "confidence": c}) for (a, b), c in self.res.inherits.items()
               if a in cls_scope]
        replace_out_links(store, "INHERITS_FROM", "CodeClass", "CodeClass", scope_cls_ids, inh)
        scope_file_ids = [self.file_id(p) for p in sorted(self.scope)]
        scope_files = set(scope_file_ids)
        imp = [LinkRow(a, b, {**STRUCT, "symbols": syms, "line": line})
               for (a, b), (syms, line) in self.res.imports.items() if a in scope_files]
        replace_out_links(store, "IMPORTS", "CodeFile", "CodeFile", scope_file_ids, imp)
        tff = [LinkRow(a, b, {"method": m, "confidence": c}) for (a, b), (m, c) in self.links.test_file_for.items()
               if a in scope_files]
        replace_out_links(store, "TEST_FILE_FOR", "CodeFile", "CodeFile", scope_file_ids, tff)
        self._emit("snapshot", dict(self.written))

    def documents(self) -> None:
        assert self.snap is not None
        store, repo = self.store, self.repo
        index = MentionIndex(files={p: self.file_id(p) for p in self.entries})
        for ref in self.snap.refs.values():
            index.add_symbol("CodeClass" if ref.sym.kind == "class" else "CodeFunction", ref.id, ref.sym.name,
                             ref.sym.qualname)
        rows: list[dict[str, Any]] = []
        section_of: list[LinkRow] = []
        sub_of: list[LinkRow] = []
        mentions: dict[str, list[LinkRow]] = {"CodeFile": [], "CodeFunction": [], "CodeClass": []}
        doc_ids: list[str] = []
        keep: set[str] = set()
        for path in sorted(self.scope):
            e = self.entries[path]
            if language_for(path).tier != 0 or e.text is None:
                continue
            secs = split_document(path, e.text)
            sec_ids = [ids.code_doc(repo, path, s.slug, s.dup) for s in secs]
            for s, sid in zip(secs, sec_ids, strict=True):
                keep.add(sid)
                doc_ids.append(sid)
                rows.append({"id": sid, "path": path, "title": s.title, "level": s.level, "text": s.text,
                             "startLine": s.start, "endLine": s.end, "deleted": False})
                section_of.append(LinkRow(sid, self.file_id(path), STRUCT))
                if s.parent is not None:
                    sub_of.append(LinkRow(sid, sec_ids[s.parent], STRUCT))
                for label, target in find_mentions(s.text, index):
                    mentions[label].append(LinkRow(sid, target, {"method": "explicit", "confidence": 1.0}))
        self._upsert("CodeDocument", rows)
        store.upsert_links("SECTION_OF", "CodeDocument", "CodeFile", section_of)
        replace_out_links(store, "SUBSECTION_OF", "CodeDocument", "CodeDocument", doc_ids, sub_of)
        for label, rel in (("CodeFile", "DOC_MENTIONS_FILE"), ("CodeFunction", "DOC_MENTIONS_FUNCTION"),
                           ("CodeClass", "DOC_MENTIONS_CLASS")):
            replace_out_links(store, rel, "CodeDocument", label, doc_ids, mentions[label])
        scope_prefixes = set(self.scope) | self.deleted_paths
        stale = [i for i, r in self.state.docs.items() if not r.get("deleted") and i not in keep
                 and ids.parse_id(i).parts["path"] in scope_prefixes]
        if stale:
            store.tombstone("CodeDocument", stale, _now())

    def manifests(self) -> None:
        store, repo = self.store, self.repo
        sources = {p: e.data for p, e in self.entries.items() if e.stored}
        comps = find_components(repo, sources)
        manifest_changed = any(m in self.scope for c in comps for m in c.manifests) or self.since_sha is None
        repo_id = ids.code_repo(repo)
        internal = internal_names(comps)
        comp_rows: list[dict[str, Any]] = []
        dep_rows: dict[str, dict[str, Any]] = {}
        uses: list[LinkRow] = []
        for c in comps:
            cid = ids.code_component(repo, c.path)
            files_in = [p for p in self.entries if component_for(p, comps) is c]
            lang = Counter(self.entries[p].language for p in files_in if self.entries[p].tier in (1, 2))
            comp_rows.append({"id": cid, "name": c.name, "path": c.path, "kind": c.kind,
                              "language": lang.most_common(1)[0][0] if lang else None, "manifest": c.manifest or None})
            for d in c.deps:
                if d.name.lower() in internal:
                    continue
                did = ids.code_dep(d.ecosystem, d.name)
                dep_rows.setdefault(did, {"id": did, "name": d.name, "ecosystem": d.ecosystem,
                                          "versionSpec": d.version_spec})
                uses.append(LinkRow(cid, did, STRUCT))
        self._upsert("CodeComponent", comp_rows)
        self._upsert("CodeDependency", list(dep_rows.values()))
        store.upsert_links("COMPONENT_IN_REPO", "CodeComponent", "CodeRepository",
                           [LinkRow(r["id"], repo_id, STRUCT) for r in comp_rows])
        comp_ids = [r["id"] for r in comp_rows]
        replace_out_links(store, "USES_PACKAGE", "CodeComponent", "CodeDependency", comp_ids, uses)
        replace_out_links(store, "COMPONENT_DEPENDS_ON", "CodeComponent", "CodeComponent", comp_ids,
                          [LinkRow(ids.code_component(repo, a.path), ids.code_component(repo, b.path), STRUCT)
                           for a, b in internal_dependencies(comps)])
        paths = sorted(self.entries) if manifest_changed else sorted(self.scope)
        fic = [LinkRow(self.file_id(p), ids.code_component(repo, component_for(p, comps).path), STRUCT) for p in paths]
        replace_out_links(store, "FILE_IN_COMPONENT", "CodeFile", "CodeComponent",
                          [self.file_id(p) for p in paths], fic)
        # files that import a declared external package
        assert self.res is not None
        pkg_links: list[LinkRow] = []
        for path, pkgs in self.res.external.items():
            if path not in self.scope:
                continue
            comp = component_for(path, comps)
            declared: dict[str, Dependency] = {}
            for c in (comp, *[x for x in comps if x.path == "."]):
                for d in c.deps:
                    declared.setdefault(d.name.lower(), d)
                    declared.setdefault(normalize(d.name), d)
            eco = "pypi" if self.parsed[path].language == "python" else "npm"
            for root, syms in pkgs.items():
                dep = package_for_import(eco, root, declared)
                if dep is not None and dep.name.lower() not in internal:
                    pkg_links.append(LinkRow(self.file_id(path), ids.code_dep(dep.ecosystem, dep.name),
                                             {**STRUCT, "symbols": sorted(syms)}))
        replace_out_links(store, "IMPORTS_PACKAGE", "CodeFile", "CodeDependency",
                          [self.file_id(p) for p in sorted(self.scope)], pkg_links)
        self.components: list[Component] = comps

    def codeowners(self) -> None:
        store, repo = self.store, self.repo
        path = next((p for p in owners_mod.CODEOWNERS_PATHS if p in self.entries and self.entries[p].stored), None)
        if path is None:
            return
        rules = owners_mod.parse_codeowners(self.entries[path].text or "")
        self._upsert("CodeOwnerRule", [{"id": ids.code_owners(repo, r.line), "pattern": r.pattern,
                                         "owners": r.owners, "line": r.line} for r in rules])
        changed = path in self.scope or self.since_sha is None
        paths = sorted(self.entries) if changed else sorted(self.scope)
        links = []
        for p in paths:
            rule = owners_mod.match_owner(p, rules)
            if rule is not None:
                links.append(LinkRow(self.file_id(p), ids.code_owners(repo, rule.line), STRUCT))
        replace_out_links(store, "MATCHES_OWNER_RULE", "CodeFile", "CodeOwnerRule",
                          [self.file_id(p) for p in paths], links)

    def write_history(self) -> None:
        store, repo = self.store, self.repo
        existing_fn = {i for i in self.state.functions} | {symbol_id(repo, p, s) for p, pf in self.parsed.items()
                                                           for s in pf.symbols if s.kind == "function"}
        existing_cls = {i for i in self.state.classes} | {symbol_id(repo, p, s) for p, pf in self.parsed.items()
                                                          for s in pf.symbols if s.kind == "class"}
        existing_files = set(self.state.files) | {self.file_id(p) for p in self.entries}
        res = write_history(store, repo, self.analysis, existing_fn, existing_cls, existing_files, set(self.entries))
        self.written["GitCommit"] += res.commits
        self.written["GitFileChange"] += res.file_changes
        nb, nt = write_refs(store, repo, self.repo_dir, self.branch)
        self.written["GitBranch"] += nb
        self.written["GitTag"] += nt
        store.query("MATCH (r:CodeRepository {id: $r})-[h:HEAD_COMMIT]->() DELETE h", {"r": ids.code_repo(repo)})
        store.upsert_links("HEAD_COMMIT", "CodeRepository", "GitCommit",
                           [LinkRow(ids.code_repo(repo), ids.git_commit(repo, self.report.head_sha), STRUCT)])
        renames = usable_renames(self.analysis, existing_fn, existing_cls)
        renames = [m for m in renames if m.old_id not in self._current_symbol_ids()]
        self.report.renames = write_renames(store, renames) + res.file_renames
        repoint_callers(store, renames)
        self._emit("git", {"commits": res.commits, "touched": res.touched})

    def _current_symbol_ids(self) -> set[str]:
        return {symbol_id(self.repo, p, s) for p, pf in self.parsed.items() for s in pf.symbols}

    def blame(self) -> None:
        if not self.do_blame:
            return
        files = {p: (self.parsed[p].symbols if p in self.parsed else []) for p in self.scope
                 if self.entries[p].stored}
        a, b = write_blame(self.store, self.repo, self.repo_dir, files)
        self._emit("blame", {"files": len(files), "file_links": a, "function_links": b})

    def metrics(self) -> None:
        result = compute_metrics(self.store)
        self.report.pagerank_method = result.pagerank_method

    def finish(self) -> CodeIngestReport:
        self.report.written = dict(self.written)
        self.report.counts = graph_counts(self.store)
        self.report.links = link_counts(self.store)
        return self.report

    def run(self) -> CodeIngestReport:
        t0 = time.perf_counter()
        for name, fn in (("walk_and_parse", self.walk_and_parse), ("resolve", self.resolve),
                         ("link_tests", self.link_tests), ("git_log", self.git_log), ("hunks", self.hunks),
                         ("write_snapshot", self.write_snapshot), ("documents", self.documents),
                         ("manifests", self.manifests), ("codeowners", self.codeowners),
                         ("write_history", self.write_history), ("blame", self.blame), ("metrics", self.metrics)):
            self._timed(name, fn)
        report = self.finish()
        report.duration_ms = int((time.perf_counter() - t0) * 1000)
        return report


def graph_counts(store: GraphStore) -> dict[str, int]:
    return {label: store.count(label) for label in CODE_LABELS}


def link_counts(store: GraphStore) -> dict[str, int]:
    out: dict[str, int] = {}
    for rel in CODE_RELS:
        rows = store.query(f"MATCH ()-[r:`{rel}`]->() RETURN count(r) AS c", read_only=True, timeout_ms=60000)
        out[rel] = int(rows[0]["c"]) if rows else 0
    return out


_INDEXED: set[str] = set()


def ensure_graph_indexes(store: GraphStore) -> None:
    if store.graph_name in _INDEXED:
        return
    from actron.graph.ontology import ensure_indexes

    ensure_indexes(store, store.ontology)
    _INDEXED.add(store.graph_name)


async def ingest_code(ws: str, repo: str, *, url: str | None = None, branch: str | None = None,
                      clone_dir: Path | None = None, depth: int | None = None, token: str | None = None,
                      emit: EventSink | None = None, since_sha: str | None = None, store: GraphStore | None = None,
                      repo_dir: Path | None = None, blame: bool = True) -> CodeIngestReport:
    """Clone or update the working branch, then ingest code and git history (full or incremental).

    `since_sha` is the stored cursor (`sync_cursors.cursor.last_sha`); None means a full backfill.
    `repo_dir` skips cloning and uses an existing checkout (tests, CLI against a local clone).
    """
    from actron.config import get_settings
    from actron.graph.store import store_for

    settings = get_settings()
    store = store or store_for(ws)
    depth = depth or settings.ACTRON_GIT_HISTORY_DEPTH
    run_id = f"code:{ws}:{repo.lower()}:{int(time.time())}"
    loop_events: list[tuple[str, dict[str, int]]] = []

    def progress(phase: str, counts: dict[str, int]) -> None:
        loop_events.append((phase, counts))

    async def flush() -> None:
        while loop_events and emit is not None:
            phase, counts = loop_events.pop(0)
            await emit("ingestion.progress", {"source": "code", "runId": run_id, "phase": phase, "counts": counts,
                                              "perMinute": None})
        loop_events.clear()

    if repo_dir is None:
        target = clone_dir_for(clone_dir or settings.ACTRON_CLONE_DIR, ws, repo)
        info: CloneInfo = await asyncio.to_thread(clone_or_fetch, url or settings.git_url(repo), target,
                                                  branch, depth, token)
        repo_dir, branch = info.path, info.branch
    if branch is None:
        from actron.connectors.code.clone import git

        branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir).stdout.decode().strip()
    await asyncio.to_thread(ensure_graph_indexes, store)
    job = CodeIngestion(store, repo, repo_dir, branch=branch, url=url or settings.git_url(repo),
                        depth=depth, since_sha=since_sha, progress=progress, blame=blame)
    t0 = time.perf_counter()
    if since_sha and since_sha == await asyncio.to_thread(head_sha, repo_dir) and since_sha:
        # nothing new: report current counts only
        job.report.head_sha = since_sha
        report = await asyncio.to_thread(job.finish)
        report.duration_ms = int((time.perf_counter() - t0) * 1000)
        return report
    for name in ("walk_and_parse", "resolve", "link_tests", "git_log", "hunks", "write_snapshot", "documents",
                 "manifests", "codeowners", "write_history", "blame", "metrics"):
        step = getattr(job, name)
        await asyncio.to_thread(job._timed, name, step)
        await flush()
    report = await asyncio.to_thread(job.finish)
    report.duration_ms = int((time.perf_counter() - t0) * 1000)
    if emit is not None:
        await emit("ingestion.progress", {"source": "code", "runId": run_id, "phase": "done",
                                          "counts": report.counts, "perMinute": None})
    return report
