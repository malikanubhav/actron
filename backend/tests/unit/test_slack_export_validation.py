"""Slack export validation: structure, sizes, path traversal, links (A-AC-91, validation side)."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest

from actron.connectors.slack_export import (
    ExportValidationError,
    extract_export,
    validate_export,
    validate_zip,
)

DAY = json.dumps([{"type": "message", "user": "U1", "text": "hi", "ts": "1700000000.000100"}])


def _zip(path: Path, entries: dict[str, str | bytes], *, symlink: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return path


GOOD = {"users.json": "[]", "channels.json": "[]", "eng/2024-01-01.json": DAY}


def test_a_ac_91_valid_zip_is_accepted(tmp_path: Path) -> None:
    """A-AC-91: structure is checked and a good zip passes."""
    report = validate_export(_zip(tmp_path / "ok.zip", GOOD))
    assert report.channels == 1 and report.day_files == 1 and report.has_users


def test_a_ac_91_zip_with_a_wrapper_folder_is_accepted(tmp_path: Path) -> None:
    report = validate_export(_zip(tmp_path / "w.zip", {f"Export/{k}": v for k, v in GOOD.items()}))
    assert report.root == "Export" and report.day_files == 1


@pytest.mark.parametrize("name", ["../evil.json", "eng/../../evil.json", "/abs/evil.json", "..\\evil.json",
                                  "C:\\evil.json", "eng/.."])
def test_a_ac_91_path_traversal_is_rejected(tmp_path: Path, name: str) -> None:
    z = _zip(tmp_path / "bad.zip", {**GOOD, name: "x"})
    with pytest.raises(ExportValidationError):
        validate_zip(z)
    with pytest.raises(ExportValidationError):
        extract_export(z, tmp_path / "out")
    assert not (tmp_path / "evil.json").exists()


def test_a_ac_91_symbolic_link_entries_are_rejected(tmp_path: Path) -> None:
    z = _zip(tmp_path / "link.zip", GOOD, symlink="eng/link.json")
    with pytest.raises(ExportValidationError, match="symbolic link"):
        validate_zip(z)


def test_a_ac_91_size_limits(tmp_path: Path) -> None:
    z = _zip(tmp_path / "ok.zip", GOOD)
    with pytest.raises(ExportValidationError, match="larger than"):
        validate_zip(z, max_archive=10)
    with pytest.raises(ExportValidationError, match="too large"):
        validate_zip(z, max_entry=5)
    with pytest.raises(ExportValidationError, match="allowed size"):
        validate_zip(z, max_total=20)
    with pytest.raises(ExportValidationError, match="more than"):
        validate_zip(z, max_entries=2)


def test_a_ac_91_zip_bomb_ratio_is_rejected(tmp_path: Path) -> None:
    z = _zip(tmp_path / "bomb.zip", {**GOOD, "eng/2024-01-02.json": b"0" * (5 * 1024 * 1024)})
    with pytest.raises(ExportValidationError, match="expands"):
        validate_zip(z)


def test_a_ac_91_missing_structure_and_bad_files(tmp_path: Path) -> None:
    with pytest.raises(ExportValidationError, match="no channel day files"):
        validate_export(_zip(tmp_path / "empty.zip", {"users.json": "[]", "readme.txt": "x"}))
    bad = tmp_path / "notzip.zip"
    bad.write_text("not a zip")
    with pytest.raises(ExportValidationError, match="not a valid zip"):
        validate_export(bad)
    txt = tmp_path / "x.txt"
    txt.write_text("x")
    with pytest.raises(ExportValidationError, match=r"folder or a \.zip"):
        validate_export(txt)
    with pytest.raises(ExportValidationError, match="not found"):
        validate_export(tmp_path / "missing")


def test_directory_export_is_validated_and_symlinks_rejected(tmp_path: Path) -> None:
    root = tmp_path / "export"
    (root / "eng").mkdir(parents=True)
    (root / "users.json").write_text("[]")
    (root / "eng" / "2024-01-01.json").write_text(DAY)
    assert validate_export(root).day_files == 1
    outside = tmp_path / "secret.json"
    outside.write_text("[]")
    (root / "eng" / "2024-01-02.json").symlink_to(outside)
    with pytest.raises(ExportValidationError, match="symbolic link"):
        validate_export(root)


def test_extract_writes_inside_the_target_only(tmp_path: Path) -> None:
    out = tmp_path / "out"
    root = extract_export(_zip(tmp_path / "ok.zip", GOOD), out)
    assert (root / "eng" / "2024-01-01.json").read_text() == DAY
    assert (root / "users.json").exists()
