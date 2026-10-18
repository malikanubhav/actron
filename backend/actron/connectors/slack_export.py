"""Slack export import (spec A, A9a): Slack's official export format instead of the live API.

An export is a folder (or `.zip`) with `users.json`, `channels.json` (optionally `groups.json`), one
folder per channel holding `YYYY-MM-DD.json` day files, and, as an extension, `events.jsonl` in
Events API shape that is applied after the history, in order. Messages map exactly like live ones
(same ids, versions and tombstones, through `actron.connectors.slack`).

Re-importing creates nothing: a day file whose hash is unchanged is skipped, and inside a changed
day file only new or edited messages are written. Zip uploads are validated before anything is
extracted: structure, sizes, path traversal and links.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from actron.config import get_settings
from actron.connectors import slack
from actron.connectors.common import (
    Batch,
    ValidationError,
    WriteResult,
    decode_token,
    encode_token,
    merge_cursor,
    write_generic,
)
from actron.connectors.steps import SOURCE_STEPS
from actron.graph import ids
from actron.graph.store import GraphStore, store_for
from actron.logging import get_logger

log = get_logger(__name__)

STEPS: list[str] = SOURCE_STEPS["slack_export"]

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRY_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 100_000
MAX_RATIO = 200
EVENTS_PAGE = 200
DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


class ExportValidationError(ValidationError):
    """The export is not usable. `reason` is a short plain sentence for the Connect screen."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason, code="invalid_export")
        self.reason = reason


@dataclass
class ExportReport:
    root: str
    channels: int = 0
    day_files: int = 0
    has_users: bool = False
    has_events: bool = False
    warnings: list[str] = field(default_factory=list)


# Validation
def _check_member_name(name: str) -> None:
    if not name or "\x00" in name:
        raise ExportValidationError("the archive has an entry with an empty or invalid name")
    if "\\" in name or re.match(r"^[A-Za-z]:", name):
        raise ExportValidationError(f"the archive entry {name!r} uses a Windows style path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ExportValidationError(f"the archive entry {name!r} would be written outside the import folder")


def validate_zip(path: Path, *, max_archive: int = MAX_ARCHIVE_BYTES, max_total: int = MAX_UNCOMPRESSED_BYTES,
                 max_entry: int = MAX_ENTRY_BYTES, max_entries: int = MAX_ENTRIES) -> list[str]:
    """Check a zip's entries without extracting. Returns the safe member names. Raises ExportValidationError."""
    if path.stat().st_size > max_archive:
        raise ExportValidationError(f"the archive is larger than {max_archive // (1024 * 1024)} MB")
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ExportValidationError("the file is not a valid zip archive") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > max_entries:
            raise ExportValidationError(f"the archive has more than {max_entries} files")
        total = 0
        names: list[str] = []
        for info in infos:
            _check_member_name(info.filename)
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise ExportValidationError(f"the archive entry {info.filename!r} is a symbolic link")
            if info.file_size > max_entry:
                raise ExportValidationError(f"the archive entry {info.filename!r} is too large")
            if info.compress_size and info.file_size > 1_000_000 and info.file_size / info.compress_size > MAX_RATIO:
                raise ExportValidationError(f"the archive entry {info.filename!r} expands suspiciously")
            total += info.file_size
            if total > max_total:
                raise ExportValidationError("the archive would expand to more than the allowed size")
            if not info.is_dir():
                names.append(info.filename)
    return names


def _structure(names: list[str]) -> ExportReport:
    """Find the export root inside a list of relative file names and check its layout."""
    parts = [PurePosixPath(n).parts for n in names]
    prefix: tuple[str, ...] = ()
    candidates = [p for p in parts if p[-1] in ("channels.json", "users.json")]
    if candidates:
        prefix = min((p[:-1] for p in candidates), key=len)
    else:
        day = [p for p in parts if len(p) >= 2 and DAY_FILE.match(p[-1])]
        if day:
            prefix = min((p[:-2] for p in day), key=len)
    rel = [p[len(prefix):] for p in parts if p[: len(prefix)] == prefix]
    report = ExportReport(root="/".join(prefix))
    channels: set[str] = set()
    for p in rel:
        if len(p) == 1 and p[0] == "users.json":
            report.has_users = True
        elif len(p) == 1 and p[0] == "events.jsonl":
            report.has_events = True
        elif len(p) == 2 and DAY_FILE.match(p[1]):
            report.day_files += 1
            channels.add(p[0])
    report.channels = len(channels)
    if report.day_files == 0:
        raise ExportValidationError("no channel day files were found; expected folders with YYYY-MM-DD.json files")
    if not report.has_users:
        report.warnings.append("users.json is missing, so names and emails are not available")
    return report


def validate_export(path: Path, **limits: int) -> ExportReport:
    """Validate a folder or a zip. Nothing is extracted."""
    path = Path(path)
    if not path.exists():
        raise ExportValidationError("the export was not found")
    if path.is_file():
        if path.suffix.lower() != ".zip":
            raise ExportValidationError("the export must be a folder or a .zip file")
        return _structure(validate_zip(path, **limits))
    root = path.resolve()
    names: list[str] = []
    for item in path.rglob("*"):
        if item.is_symlink():
            raise ExportValidationError(f"the export contains a symbolic link: {item.name}")
        if item.is_file():
            if root not in item.resolve().parents:
                raise ExportValidationError(f"{item.name} is outside the export folder")
            names.append(item.relative_to(path).as_posix())
    return _structure(names)


def extract_export(zip_path: Path, dest: Path) -> Path:
    """Validate and extract a zip into `dest` (created). Returns the export root inside it."""
    names = validate_zip(zip_path)
    report = _structure(names)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = (base / info.filename).resolve()
            if base not in target.parents:
                raise ExportValidationError(f"the archive entry {info.filename!r} would leave the import folder")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1024 * 1024):
                    out.write(chunk)
    return base / report.root if report.root else base


def export_dir(ws: str) -> Path:
    return get_settings().ACTRON_CLONE_DIR / ws / "slack_export"


_ROOTS: dict[str, Path] = {}


def resolve_root(ws: str, config: Mapping[str, Any]) -> Path:
    """The folder to read: `config.path` as is, or the zip extracted under ACTRON_CLONE_DIR/<ws>/slack_export.

    Validation walks the whole export, so the answer is remembered for the life of the process.
    """
    raw = config.get("path")
    if not raw:
        raise ExportValidationError("no export path is configured")
    key = f"{ws}|{raw}"
    cached = _ROOTS.get(key)
    if cached is not None and cached.exists():
        return cached
    root = _resolve_root(ws, Path(str(raw)))
    _ROOTS[key] = root
    return root


def _resolve_root(ws: str, path: Path) -> Path:
    if path.is_file():
        digest = hashlib.sha256(str(path.resolve()).encode() + str(path.stat().st_mtime_ns).encode()).hexdigest()[:12]
        dest = export_dir(ws) / digest
        if not dest.exists():
            tmp = dest.with_suffix(".partial")
            return_root = extract_export(path, tmp)
            tmp.rename(dest)
            return dest / return_root.relative_to(tmp)
        report = _structure([p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()])
        return dest / report.root if report.root else dest
    validate_export(path)
    report = _structure([p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()])
    return path / report.root if report.root else path


# Reading
def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, UnicodeDecodeError) as exc:
        raise ExportValidationError(f"{path.name} is not valid JSON: {exc}") from None


def _team_id(root: Path, users: list[dict[str, Any]], path: Path) -> str:
    for u in users:
        if u.get("team_id"):
            return str(u["team_id"])
    for chan_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for day in sorted(chan_dir.glob("*.json"))[:1]:
            data = _read_json(day)
            for m in data or []:
                if isinstance(m, dict) and m.get("team"):
                    return str(m["team"])
    return "export-" + hashlib.sha256(str(path).encode()).hexdigest()[:10]


def _channels(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fname, private in (("channels.json", False), ("groups.json", True)):
        for c in _read_json(root / fname) or []:
            if isinstance(c, dict) and c.get("id") and c.get("name"):
                out.append({**c, "is_private": private or c.get("is_private", False)})
    if not out:  # no channels.json: derive ids from folder names
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            out.append({"id": d.name, "name": d.name})
    return out


def _aliases(c: Mapping[str, Any]) -> list[str] | None:
    found: list[str] = []
    for key in ("original_id", "previous_id"):
        if c.get(key) and c[key] != c["id"]:
            found.append(str(c[key]))
    for a in c.get("aliases") or []:
        if a != c["id"] and a not in found:
            found.append(str(a))
    return found or None


def _day_files(root: Path, dirname: str) -> list[Path]:
    d = root / dirname
    return sorted(p for p in d.glob("*.json") if DAY_FILE.match(p.name)) if d.is_dir() else []


# Steps
async def fetch_page(ws: str, step: str, cursor: Mapping[str, Any], page_token: str | None,
                     config: Mapping[str, Any]) -> Batch:
    if step not in STEPS:
        raise ValueError(f"unknown Slack export step {step!r}")
    root = await asyncio.to_thread(resolve_root, ws, config)
    batch = Batch(step=step)
    tok = decode_token(page_token)
    await asyncio.to_thread(_STEP_FUNCS[step], ws, root, cursor, tok, config, batch)
    return batch


def _step_workspace(ws: str, root: Path, cursor: Mapping[str, Any], tok: dict[str, Any],
                    config: Mapping[str, Any], b: Batch) -> None:
    users = _read_json(root / "users.json") or []
    team = _team_id(root, users, Path(str(config.get("path"))))
    domain = config.get("domain")
    b.add_node("SlackWorkspace", {"id": ids.slack_workspace(team), "name": config.get("name") or team,
                                  "domain": domain})
    b.cursor_update["workspace"] = {"id": team, "domain": domain, "bot_user_id": None}


def _step_users(ws: str, root: Path, cursor: Mapping[str, Any], tok: dict[str, Any],
                config: Mapping[str, Any], b: Batch) -> None:
    users = [u for u in (_read_json(root / "users.json") or []) if isinstance(u, dict) and u.get("id")]
    start = int(tok.get("o", 0))
    wid = (cursor.get("workspace") or {}).get("id")
    for u in users[start : start + 200]:
        row = slack.user_row(u)
        b.add_node("SlackUser", row)
        if wid:
            b.add_link("RELATED_TO", "SlackUser", row["id"], "SlackWorkspace", ids.slack_workspace(wid))
    if start + 200 < len(users):
        b.next_page_token = encode_token({"o": start + 200})


def _step_channels(ws: str, root: Path, cursor: Mapping[str, Any], tok: dict[str, Any],
                   config: Mapping[str, Any], b: Batch) -> None:
    wid = (cursor.get("workspace") or {}).get("id")
    dirs: dict[str, str] = {}
    for c in _channels(root):
        row = slack.channel_row(c)
        row["aliases"] = _aliases(c)
        row["created_at"] = _iso_epoch(c.get("created"))
        b.add_node("SlackChannel", row)
        dirs[c["id"]] = c["name"]
        if wid:
            b.add_link("RELATED_TO", "SlackChannel", row["id"], "SlackWorkspace", ids.slack_workspace(wid))
        for uid in c.get("members") or []:
            b.add_link("RELATED_TO_CHANNEL", "SlackUser", ids.slack_user(uid), "SlackChannel", row["id"])
    b.cursor_update["_dirs"] = dirs


def _iso_epoch(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return None


def _step_history(ws: str, root: Path, cursor: Mapping[str, Any], tok: dict[str, Any],
                  config: Mapping[str, Any], b: Batch) -> None:
    dirs: dict[str, str] = dict(cursor.get("_dirs") or {})
    channel_ids = sorted(dirs)
    i, d = int(tok.get("i", 0)), int(tok.get("d", 0))
    while i < len(channel_ids) and d >= len(_day_files(root, dirs[channel_ids[i]])):
        i, d = i + 1, 0
    if i >= len(channel_ids):
        return
    cid = channel_ids[i]
    files = _day_files(root, dirs[cid])
    path = files[d]
    key = f"{dirs[cid]}/{path.name}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    seen: dict[str, str] = dict(cursor.get("files") or {})
    if seen.get(key) != digest:
        data = _read_json(path)
        if not isinstance(data, list):
            raise ExportValidationError(f"{key} must contain a list of messages")
        _plan_day(ws, b, cid, data, slack.ctx_from_cursor(cursor))
        b.cursor_update["files"] = {key: digest}
    # advance to the next day file or channel
    if d + 1 < len(files):
        b.next_page_token = encode_token({"i": i, "d": d + 1})
    elif i + 1 < len(channel_ids):
        b.next_page_token = encode_token({"i": i + 1, "d": 0})


DELETED_SUBTYPES = frozenset({"tombstone", "message_deleted"})


def _plan_day(ws: str, b: Batch, cid: str, raws: list[dict[str, Any]], ctx: slack.MsgCtx) -> None:
    normal: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = b.extra.setdefault("deleted", [])
    for raw in raws:
        if not isinstance(raw, dict):
            continue
        subtype = raw.get("subtype")
        if subtype in DELETED_SUBTYPES:
            ts = raw.get("deleted_ts") or raw.get("ts")
            if ts:
                row = slack.message_row(cid, {**raw, "ts": ts, "subtype": None}, ctx) if raw.get("ts") else None
                deleted.append({"id": ids.slack_msg(cid, str(ts)), "row": row})
            continue
        normal.append(raw)
    store = store_for(ws)
    slack.plan_messages(store, b, cid, normal, ctx)


def _step_events(ws: str, root: Path, cursor: Mapping[str, Any], tok: dict[str, Any],
                 config: Mapping[str, Any], b: Batch) -> None:
    path = Path(str(config["events"])) if config.get("events") else root / "events.jsonl"
    if not path.is_file():
        return
    offset = int(cursor.get("events_offset") or 0)
    lines = path.read_text(encoding="utf-8").splitlines()
    chunk = lines[offset : offset + EVENTS_PAGE]
    names = {v: k for k, v in (cursor.get("_dirs") or {}).items()}
    events: list[dict[str, Any]] = []
    for n, line in enumerate(chunk, start=offset + 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            raise ExportValidationError(f"events.jsonl line {n} is not valid JSON") from None
        event = obj.get("event") if isinstance(obj, dict) and isinstance(obj.get("event"), dict) else obj
        if isinstance(event, dict):
            if event.get("channel") in names:
                event = {**event, "channel": names[event["channel"]]}
            events.append(event)
    b.extra["events"] = events
    b.cursor_update["events_offset"] = offset + len(chunk)
    if offset + EVENTS_PAGE < len(lines):
        b.next_page_token = encode_token({"o": offset + EVENTS_PAGE})


_STEP_FUNCS = {
    "workspace": _step_workspace, "users": _step_users, "channels": _step_channels,
    "history": _step_history, "events": _step_events,
}


# Writing
def write_batch(ws: str, step: str, batch: Batch) -> WriteResult:
    store = store_for(ws)
    changed: list[str] = []
    entries = batch.extra.get("messages", [])
    created = slack.apply_message_ops(store, entries, changed)
    result = write_generic(ws, batch, store=store)
    if created:
        result.counts["SlackMessage"] = result.counts.get("SlackMessage", 0) + created
    unlink = batch.extra.get("unlink_reactions") or []
    if unlink:
        store.delete_links("RELATED_TO_REACTION", "SlackMessage", "SlackReaction", [(a, c) for a, c in unlink])
    for item in batch.extra.get("deleted", []):
        _tombstone(store, item, result)
    if batch.extra.get("events"):
        ctx = slack.ctx_from_cursor({"workspace": {}})
        applied = 0
        for event in batch.extra["events"]:
            outcome = slack._apply_event(ws, event, ctx)  # same code path as live events
            if outcome.kind not in ("ignored",):
                applied += 1
            if outcome.kind in ("new", "edited", "deleted"):
                changed.extend(outcome.changed_ids)
        if applied:
            result.counts["events"] = applied
    result.changed_ids = list(dict.fromkeys([*changed, *result.changed_ids]))
    return result


def _tombstone(store: GraphStore, item: Mapping[str, Any], result: WriteResult) -> None:
    mid = item["id"]
    if store.get_node(mid) is not None:
        if (store.get_node(mid) or {}).get("deleted"):
            return
        slack.tombstone_message(store, mid)
        result.counts["SlackMessage"] = result.counts.get("SlackMessage", 0) + 1
        return
    row = item.get("row")
    if row:  # a placeholder for a deleted message that was never imported: keep it as a tombstone
        store.upsert_nodes("SlackMessage", [row])
        store.tombstone("SlackMessage", [mid])
        result.counts["SlackMessage"] = result.counts.get("SlackMessage", 0) + 1


# A plain loop for the CLI (`actron ingest slack-export <path>`): the same steps without Temporal
async def run_import(ws: str, config: Mapping[str, Any]) -> tuple[dict[str, int], dict[str, Any]]:
    cursor: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for step in STEPS:
        token: str | None = None
        while True:
            batch = await fetch_page(ws, step, cursor, token, config)
            result = await asyncio.to_thread(write_batch, ws, step, batch)
            cursor = merge_cursor(cursor, batch.cursor_update)
            for k, v in result.counts.items():
                counts[k] = counts.get(k, 0) + v
            token = batch.next_page_token
            if token is None:
                break
    return counts, cursor
