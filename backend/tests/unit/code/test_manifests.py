"""A-AC-33: manifests produce components, dependencies and component dependencies (two-package monorepo)."""

from __future__ import annotations

import json

from actron.connectors.code.manifests import (
    component_for,
    find_components,
    internal_dependencies,
    package_for_import,
)

SOURCES = {
    "package.json": json.dumps({"name": "mono", "private": True, "workspaces": ["packages/*"],
                                "devDependencies": {"typescript": "^5.4.0"}}).encode(),
    "packages/core/package.json": json.dumps({"name": "@mono/core", "dependencies": {"lodash": "^4.17.21"}}).encode(),
    "packages/web/package.json": json.dumps({"name": "@mono/web", "dependencies": {"@mono/core": "workspace:*",
                                                                                "react": "18.3.1"},
                                             "devDependencies": {"mocha": "^10"}}).encode(),
    "tools/py/pyproject.toml": b'[project]\nname = "tools"\ndependencies = ["requests>=2.31", "PyYAML"]\n'
                               b'[project.optional-dependencies]\ndev = ["pytest; python_version>\'3.8\'"]\n',
    "tools/py/requirements-dev.txt": b"# dev\nruff==0.5.0\n-r other.txt\n",
    "node_modules/x/package.json": b'{"name": "ignored"}',
}


def test_components_and_dependencies() -> None:
    """A-AC-33"""
    comps = {c.path: c for c in find_components("acme/mono", SOURCES)}
    assert set(comps) == {".", "packages/core", "packages/web", "tools/py"}
    assert comps["packages/web"].name == "@mono/web"
    web_deps = {(d.ecosystem, d.name, d.version_spec) for d in comps["packages/web"].deps}
    assert ("npm", "react", "18.3.1") in web_deps and ("npm", "mocha", "^10") in web_deps
    py = {d.name for d in comps["tools/py"].deps}
    assert py == {"requests", "PyYAML", "pytest", "ruff"}
    assert comps["."].workspaces == ["packages/*"]
    pairs = {(a.name, b.name) for a, b in internal_dependencies(list(comps.values()))}
    assert pairs == {("@mono/web", "@mono/core")}


def test_nearest_manifest_wins() -> None:
    """A-AC-33"""
    comps = find_components("acme/mono", SOURCES)
    assert component_for("packages/web/src/app.tsx", comps).path == "packages/web"
    assert component_for("README.md", comps).path == "."
    assert component_for("packages/webx/a.ts", comps).path == "."


def test_repo_without_manifest_has_root_component() -> None:
    """A-AC-33"""
    comps = find_components("acme/plain", {"main.py": b"print(1)\n"})
    assert [(c.path, c.name) for c in comps] == [(".", "plain")]


def test_import_to_package() -> None:
    """A-AC-33"""
    comps = {c.path: c for c in find_components("acme/mono", SOURCES)}
    declared = {d.name.lower(): d for d in comps["tools/py"].deps}
    declared.update({d.name.lower().replace("_", "-"): d for d in comps["tools/py"].deps})
    assert package_for_import("pypi", "yaml", declared) is not None
    assert package_for_import("pypi", "os", declared) is None
