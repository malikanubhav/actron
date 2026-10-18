"""Components and dependencies from manifests (spec A, A6.8).

Supported: pyproject.toml (`[project]`, optional dependencies, `[tool.poetry]`), setup.cfg, requirements*.txt,
package.json (name, dependencies, devDependencies, peerDependencies, workspaces), pnpm-workspace.yaml.
Each manifest directory is a component; files belong to the nearest manifest directory above them.
"""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

MANIFEST_NAMES = ("pyproject.toml", "setup.cfg", "package.json", "pnpm-workspace.yaml")
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
# import name -> distribution name, for the common cases where they differ
PY_IMPORT_ALIASES = {"yaml": "pyyaml", "PIL": "pillow", "sklearn": "scikit-learn", "bs4": "beautifulsoup4",
                     "dateutil": "python-dateutil", "jwt": "pyjwt", "dotenv": "python-dotenv", "attr": "attrs",
                     "cv2": "opencv-python", "google.protobuf": "protobuf", "magic": "python-magic"}


@dataclass
class Dependency:
    ecosystem: str
    name: str
    version_spec: str | None = None


@dataclass
class Component:
    path: str  # directory, "." for the root
    name: str
    manifests: list[str] = field(default_factory=list)
    deps: list[Dependency] = field(default_factory=list)
    workspaces: list[str] = field(default_factory=list)
    kind: str = "package"

    @property
    def manifest(self) -> str:
        return self.manifests[0] if self.manifests else ""

    @property
    def ecosystem(self) -> str | None:
        return self.deps[0].ecosystem if self.deps else None


def is_manifest(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in MANIFEST_NAMES or bool(re.match(r"^requirements.*\.txt$", name))


def _req_name(spec: str) -> tuple[str, str | None] | None:
    spec = spec.split(";", 1)[0].split("#", 1)[0].strip()
    if not spec or spec.startswith(("-", "git+", "http")):
        return None
    m = _REQ_NAME.match(spec)
    if not m:
        return None
    name = m.group(1)
    rest = spec[m.end():].strip()
    rest = re.sub(r"^\[[^\]]*\]", "", rest).strip()
    return name, rest or None


def _pyproject(text: str, comp: Component) -> None:
    data = tomllib.loads(text)
    project = data.get("project") or {}
    if project.get("name"):
        comp.name = str(project["name"])
    for spec in project.get("dependencies") or []:
        got = _req_name(str(spec))
        if got:
            comp.deps.append(Dependency("pypi", got[0], got[1]))
    for group in (project.get("optional-dependencies") or {}).values():
        for spec in group or []:
            got = _req_name(str(spec))
            if got:
                comp.deps.append(Dependency("pypi", got[0], got[1]))
    for group in (data.get("dependency-groups") or {}).values():
        for spec in group or []:
            if isinstance(spec, str):
                got = _req_name(spec)
                if got:
                    comp.deps.append(Dependency("pypi", got[0], got[1]))
    poetry = (data.get("tool") or {}).get("poetry") or {}
    if poetry.get("name") and not project.get("name"):
        comp.name = str(poetry["name"])
    tables: list[dict[str, Any]] = [poetry.get("dependencies") or {}, poetry.get("dev-dependencies") or {}]
    for grp in (poetry.get("group") or {}).values():
        tables.append((grp or {}).get("dependencies") or {})
    for table in tables:
        for name, spec in table.items():
            if name.lower() == "python":
                continue
            comp.deps.append(Dependency("pypi", name, spec if isinstance(spec, str) else None))


def _setup_cfg(text: str, comp: Component) -> None:
    cp = configparser.ConfigParser()
    try:
        cp.read_string(text)
    except configparser.Error:
        return
    if cp.has_option("metadata", "name"):
        comp.name = cp.get("metadata", "name")
    if cp.has_option("options", "install_requires"):
        for line in cp.get("options", "install_requires").splitlines():
            got = _req_name(line)
            if got:
                comp.deps.append(Dependency("pypi", got[0], got[1]))


def _requirements(text: str, comp: Component) -> None:
    for line in text.splitlines():
        got = _req_name(line)
        if got:
            comp.deps.append(Dependency("pypi", got[0], got[1]))


def _package_json(text: str, comp: Component) -> None:
    data = json.loads(text)
    if not isinstance(data, dict):
        return
    if data.get("name"):
        comp.name = str(data["name"])
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name, spec in (data.get(key) or {}).items():
            comp.deps.append(Dependency("npm", str(name), str(spec) if spec is not None else None))
    ws = data.get("workspaces")
    if isinstance(ws, dict):
        ws = ws.get("packages")
    if isinstance(ws, list):
        comp.workspaces.extend(str(w) for w in ws)


def _pnpm(text: str, comp: Component) -> None:
    data = yaml.safe_load(text) or {}
    if isinstance(data, dict):
        comp.workspaces.extend(str(p) for p in data.get("packages") or [])


def find_components(repo: str, sources: dict[str, bytes]) -> list[Component]:
    comps: dict[str, Component] = {}
    for path in sorted(sources):
        if not is_manifest(path):
            continue
        p = PurePosixPath(path)
        if any(part in ("node_modules", "vendor", "dist", "build") for part in p.parts[:-1]):
            continue
        d = str(p.parent)
        comp = comps.setdefault(d, Component(path=d, name=(repo.split("/")[-1] if d == "." else p.parent.name)))
        comp.manifests.append(path)
        text = sources[path].decode("utf-8", "replace")
        try:
            if p.name == "pyproject.toml":
                _pyproject(text, comp)
            elif p.name == "setup.cfg":
                _setup_cfg(text, comp)
            elif p.name == "package.json":
                _package_json(text, comp)
            elif p.name == "pnpm-workspace.yaml":
                _pnpm(text, comp)
            else:
                _requirements(text, comp)
        except (ValueError, tomllib.TOMLDecodeError, yaml.YAMLError):
            continue
    if "." not in comps:
        comps["."] = Component(path=".", name=repo.split("/")[-1])
    for comp in comps.values():
        if any(part.lower() in ("test", "tests", "e2e") for part in PurePosixPath(comp.path).parts):
            comp.kind = "tests"
        # same package listed twice (for example dependencies and devDependencies): keep the first
        seen: set[tuple[str, str]] = set()
        unique: list[Dependency] = []
        for dep in comp.deps:
            key = (dep.ecosystem, dep.name.lower())
            if key not in seen:
                seen.add(key)
                unique.append(dep)
        comp.deps = unique
    return sorted(comps.values(), key=lambda c: c.path)


def component_for(path: str, comps: list[Component]) -> Component:
    """Nearest manifest directory above the file (the root component otherwise)."""
    best = next(c for c in comps if c.path == ".")
    for comp in comps:
        if comp.path != "." and path.startswith(comp.path + "/") and (
                best.path == "." or len(comp.path) > len(best.path)):
            best = comp
    return best


def internal_dependencies(comps: list[Component]) -> list[tuple[Component, Component]]:
    by_name = {c.name.lower(): c for c in comps}
    out: list[tuple[Component, Component]] = []
    for comp in comps:
        for dep in comp.deps:
            target = by_name.get(dep.name.lower())
            if target is not None and target is not comp:
                out.append((comp, target))
    return out


def internal_names(comps: list[Component]) -> set[str]:
    return {c.name.lower() for c in comps}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def package_for_import(ecosystem: str, root: str, declared: dict[str, Dependency]) -> Dependency | None:
    """Match an import root (`yaml`, `@scope/pkg`) to a declared dependency."""
    if ecosystem == "pypi":
        cand = PY_IMPORT_ALIASES.get(root, root)
        return declared.get(normalize(cand)) or declared.get(normalize(root))
    return declared.get(root.lower()) or declared.get(f"@types/{root}".lower())
