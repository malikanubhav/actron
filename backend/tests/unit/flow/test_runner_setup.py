"""Test runner setup found by the first live build of Calva: Node env, the ClojureScript build, Pi's protocol."""

from __future__ import annotations

import json
from pathlib import Path

from actron.flow import test_runner as tr
from actron.flow.build import WORK_PROTOCOL


def _repo(tmp_path: Path, *, scripts: dict[str, str], shadow: bool = True) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "package.json").write_text(json.dumps({"scripts": scripts}))
    (tmp_path / "package-lock.json").write_text("{}")
    if shadow:
        (tmp_path / "shadow-cljs.edn").write_text("{}")
    return tmp_path


def test_node_tests_run_without_native_type_stripping(tmp_path: Path) -> None:
    """Node 22.18+ strips types natively and bypasses ts-node; the run must turn that off."""
    plans = tr.plan_dependencies(_repo(tmp_path, scripts={}))
    node = next(p for p in plans if p.kind == "node")
    assert node.run_env == {"NODE_OPTIONS": "--no-experimental-strip-types"}


def test_cljs_build_is_needed_only_for_shadow_projects_with_the_script(tmp_path: Path) -> None:
    repo = _repo(tmp_path, scripts={"compile-cljs": "npx shadow-cljs compile x"})
    assert tr.needs_cljs_build(repo) is True
    (repo / "out" / "cljs-lib").mkdir(parents=True)
    (repo / tr.CLJS_OUTPUT).write_text("//")
    assert tr.needs_cljs_build(repo) is False  # already built


def test_cljs_build_not_needed_without_script_or_shadow_config(tmp_path: Path) -> None:
    assert tr.needs_cljs_build(_repo(tmp_path / "x", scripts={"test": "mocha"})) is False
    assert tr.needs_cljs_build(_repo(tmp_path / "y", scripts={"compile-cljs": "x"}, shadow=False)) is False


def test_protocol_forbids_installing_and_tells_pi_what_to_do_when_tests_cannot_run() -> None:
    assert "do not install, download or build anything" in WORK_PROTOCOL
    assert "Never install packages or toolchains" in WORK_PROTOCOL
    assert "Stop after two runs" in WORK_PROTOCOL
    assert "very first action" in WORK_PROTOCOL
