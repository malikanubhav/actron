"""Call, import and inheritance resolution over one snapshot (spec A, A6.6).

Tiers and confidences: `local` 1.0 (same scope chain or file/package), `self` 0.95 (`self.x()`, `this.x()`,
`super().x()`; stored as resolution `local` because the ontology lists local, import, project, name_only),
`import` 0.95 (dynamic `import()`/`require()` 0.6), `project` 0.7 (unique qualified-name match), `name_only`
0.4 (unique function name). Tier-2 languages are capped at 0.6. Ambiguous name-only calls create no edge and
count as unresolved; so do bare-name calls in tier-1 languages that match nothing and are not builtins.
Calls through external packages create no edge and are not counted.
"""

from __future__ import annotations

import builtins
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from actron.connectors.code.model import CallSite, ImportRec, ParsedFile, Symbol
from actron.graph import ids

CONF = {"local": 1.0, "self": 0.95, "import": 0.95, "dynamic": 0.6, "project": 0.7, "name_only": 0.4}
TIER2_CAP = 0.6

FAMILY = {"python": "py", "typescript": "js", "tsx": "js", "javascript": "js", "go": "go", "java": "java",
          "rust": "rust", "clojure": "clj", "kotlin": "kotlin", "ruby": "ruby", "php": "php", "c": "c",
          "cpp": "c", "scala": "scala", "swift": "swift"}

PY_BUILTINS = frozenset(dir(builtins)) | {"super", "self", "cls"}
JS_GLOBALS = frozenset(["console", "Math", "JSON", "Object", "Array", "Promise", "String", "Number", "Boolean", "Date", "Error", "TypeError", "RangeError", "RegExp", "Map", "Set", "WeakMap", "WeakSet", "Symbol", "BigInt", "Proxy", "Reflect", "parseInt", "parseFloat", "isNaN", "isFinite", "setTimeout", "clearTimeout", "setInterval", "clearInterval", "setImmediate", "queueMicrotask", "require", "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI", "fetch", "Buffer", "process", "structuredClone", "expect", "describe", "it", "test", "suite", "context", "specify", "before", "after", "beforeEach", "afterEach", "beforeAll", "afterAll", "suiteSetup", "suiteTeardown", "setup", "teardown", "jest", "sinon", "assert", "alert", "document", "window", "globalThis", "Intl", "URL", "URLSearchParams", "TextEncoder", "TextDecoder", "AbortController", "atob", "btoa", "Uint8Array", "ArrayBuffer", "DataView", "Function", "eval", "import", "super"])
GO_BUILTINS = frozenset(["len", "cap", "make", "new", "append", "copy", "delete", "panic", "recover", "print", "println", "close", "complex", "real", "imag", "min", "max", "clear", "string", "int", "int64", "int32", "uint", "uint8", "byte", "rune", "float64", "float32", "bool", "error", "any"])
JAVA_BUILTINS = frozenset({"super", "this"})
RUST_BUILTINS = frozenset(["Some", "None", "Ok", "Err", "Box", "Vec", "String", "drop", "panic", "Default", "Into", "From"])
_BUILTINS = {"py": PY_BUILTINS, "js": JS_GLOBALS, "go": GO_BUILTINS, "java": JAVA_BUILTINS, "rust": RUST_BUILTINS}
_SELF_NAMES = frozenset({"self", "cls", "this", "@", "$this"})


@dataclass
class SymRef:
    path: str
    sym: Symbol
    id: str
    family: str
    tier: int


@dataclass
class Binding:
    kind: str  # module, symbol, external
    path: str | None = None  # target file (module) or the file defining the symbol
    paths: tuple[str, ...] = ()  # Go/Java package: several files
    name: str | None = None  # symbol name in the target module
    package: str | None = None  # external package root
    dynamic: bool = False


@dataclass
class Edge:
    resolution: str
    confidence: float
    lines: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.lines)


@dataclass
class Resolution:
    calls: dict[tuple[str, str], Edge] = field(default_factory=dict)
    instantiates: dict[tuple[str, str], Edge] = field(default_factory=dict)
    inherits: dict[tuple[str, str], float] = field(default_factory=dict)
    imports: dict[tuple[str, str], tuple[list[str], int]] = field(default_factory=dict)  # file ids
    external: dict[str, dict[str, set[str]]] = field(default_factory=dict)  # path -> package -> symbols
    unresolved: dict[str, int] = field(default_factory=dict)  # function id -> count
    tiers: dict[str, int] = field(default_factory=dict)  # resolution counts for reporting

    @property
    def unresolved_total(self) -> int:
        return sum(self.unresolved.values())


def symbol_id(repo: str, path: str, sym: Symbol) -> str:
    if sym.kind == "class":
        return ids.code_class(repo, path, sym.qualname, sym.dup)
    return ids.code_fn(repo, path, sym.qualname, sym.dup)


def strip_jsonc(raw: str) -> str:
    out: list[str] = []
    i, n = 0, len(raw)
    in_str = False
    while i < n:
        ch = raw[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(raw[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif raw.startswith("//", i):
            j = raw.find("\n", i)
            i = n if j < 0 else j
        elif raw.startswith("/*", i):
            j = raw.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


@dataclass
class TsPaths:
    base_dir: str  # directory of tsconfig.json joined with baseUrl ("" for repo root)
    paths: dict[str, list[str]]
    has_base_url: bool


def read_tsconfig(text: str, tsconfig_path: str) -> TsPaths | None:
    try:
        data = json.loads(strip_jsonc(text))
    except (json.JSONDecodeError, ValueError):
        return None
    opts = data.get("compilerOptions") or {}
    root = str(PurePosixPath(tsconfig_path).parent)
    root = "" if root == "." else root
    base = opts.get("baseUrl")
    base_dir = _join(root, base) if base else root
    paths = opts.get("paths") or {}
    return TsPaths(base_dir=base_dir, paths={k: list(v) for k, v in paths.items() if isinstance(v, list)},
                   has_base_url=bool(base))


def _join(*parts: str) -> str:
    stack: list[str] = []
    for part in parts:
        for seg in part.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if stack:
                    stack.pop()
            else:
                stack.append(seg)
    return "/".join(stack)


_TS_EXTS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", "/index.ts", "/index.tsx", "/index.js",
            "/index.jsx")


class Snapshot:
    """Symbol tables for one snapshot of a repository."""

    def __init__(self, repo: str, files: dict[str, ParsedFile], all_paths: set[str],
                 tsconfigs: dict[str, TsPaths] | None = None, go_module: str | None = None) -> None:
        self.repo = repo
        self.files = files
        self.all_paths = all_paths
        self.tsconfigs = tsconfigs or {}
        self.go_module = go_module
        self.refs: dict[str, SymRef] = {}  # id -> ref
        self.by_file: dict[str, dict[str, SymRef]] = {}  # path -> key -> ref
        self.top: dict[str, dict[str, SymRef]] = {}  # path -> top-level name -> ref (first definition)
        self.children: dict[str, dict[str, SymRef]] = defaultdict(dict)  # parent id -> name -> ref
        self.methods: dict[str, dict[str, SymRef]] = defaultdict(dict)  # class id -> name -> method ref
        self.fn_by_name: dict[tuple[str, str], list[SymRef]] = defaultdict(list)
        self.cls_by_name: dict[tuple[str, str], list[SymRef]] = defaultdict(list)
        self.by_qual: dict[tuple[str, str], list[SymRef]] = defaultdict(list)
        self.py_modules: dict[str, str] = {}
        self.clj_ns: dict[str, str] = {}
        self.dir_files: dict[str, list[str]] = defaultdict(list)
        self.bindings: dict[str, dict[str, Binding]] = {}
        self.bases: dict[str, list[tuple[str, float]]] = {}
        self._index()

    # Indexing
    def _index(self) -> None:
        for path, pf in self.files.items():
            fam = FAMILY.get(pf.language, pf.language)
            keyed: dict[str, SymRef] = {}
            for sym in pf.symbols:
                ref = SymRef(path, sym, symbol_id(self.repo, path, sym), fam, pf.tier)
                self.refs[ref.id] = ref
                keyed[sym.key] = ref
            self.by_file[path] = keyed
            top: dict[str, SymRef] = {}
            for ref in keyed.values():
                sym = ref.sym
                if sym.parent is None:
                    top.setdefault(sym.name, ref)
                else:
                    parent = keyed.get(sym.parent)
                    if parent is not None:
                        self.children[parent.id].setdefault(sym.name, ref)
                        if parent.sym.kind == "class" and sym.kind == "function":
                            self.methods[parent.id].setdefault(sym.name, ref)
                if sym.kind == "function":
                    self.fn_by_name[(fam, sym.name)].append(ref)
                else:
                    self.cls_by_name[(fam, sym.name)].append(ref)
                self.by_qual[(fam, sym.qualname)].append(ref)
            # Go and Rust methods defined outside their type: index by `Type.method` / `Type::method`
            for ref in keyed.values():
                sym = ref.sym
                if sym.kind == "function" and sym.parent is None and sym.fn_kind == "method":
                    sep = "::" if "::" in sym.qualname else "."
                    owner = sym.qualname.rsplit(sep, 1)[0].rsplit(sep, 1)[-1]
                    for cls in self.cls_by_name.get((fam, owner), []):
                        if cls.path == path or fam == "go":
                            self.methods[cls.id].setdefault(sym.name, ref)
            self.top[path] = top
            self.dir_files[str(PurePosixPath(path).parent)].append(path)
            if pf.language == "python":
                mod = path[:-3] if path.endswith(".py") else path[:-4]
                mod = mod.replace("/", ".")
                mod = mod.removesuffix(".__init__")
                self.py_modules.setdefault(mod, path)
                for prefix in ("src.", "lib."):
                    if mod.startswith(prefix):
                        self.py_modules.setdefault(mod[len(prefix):], path)
            if pf.language == "clojure" and pf.namespace:
                self.clj_ns.setdefault(pf.namespace, path)
        # Go methods across files of one package
        for path, pf in self.files.items():
            if pf.language != "go":
                continue
            for sym in pf.symbols:
                if sym.kind == "function" and "." in sym.qualname:
                    owner = sym.qualname.split(".", 1)[0]
                    for d_path in self.dir_files[str(PurePosixPath(path).parent)]:
                        owner_ref = self.top.get(d_path, {}).get(owner)
                        if owner_ref is not None and owner_ref.sym.kind == "class":
                            self.methods[owner_ref.id].setdefault(sym.name, self.by_file[path][sym.key])
        for path, pf in self.files.items():
            self.bindings[path] = self._bindings(path, pf)
        for ref in list(self.refs.values()):
            if ref.sym.kind == "class" and ref.sym.bases:
                self.bases[ref.id] = self._resolve_bases(ref)

    # Imports
    def _bindings(self, path: str, pf: ParsedFile) -> dict[str, Binding]:
        out: dict[str, Binding] = {}
        lang = pf.language
        for imp in pf.imports:
            if lang == "python":
                self._py_import(path, imp, out)
            elif lang in ("typescript", "tsx", "javascript"):
                self._ts_import(path, imp, out)
            elif lang == "go":
                self._go_import(imp, out)
            elif lang == "java":
                self._java_import(imp, out)
            elif lang == "rust":
                self._rust_import(path, imp, out)
            elif lang == "clojure":
                self._clj_import(imp, out)
        return out

    def _py_import(self, path: str, imp: ImportRec, out: dict[str, Binding]) -> None:
        module = imp.module
        if imp.level:
            base = list(PurePosixPath(path).parent.parts)
            if imp.level > 1:
                base = base[: len(base) - (imp.level - 1)] if imp.level - 1 <= len(base) else []
            module = ".".join([*base, *([module] if module else [])])
        if not imp.names and not imp.star:  # import a.b [as c]
            target = self.py_modules.get(module)
            if imp.alias:
                out[imp.alias] = Binding("module", path=target) if target else Binding(
                    "external", package=module.split(".")[0])
            else:
                root = module.split(".")[0]
                root_path = self.py_modules.get(root)
                if target or root_path:
                    out.setdefault(root, Binding("module", path=root_path, name=None))
                    out[f"__pkg__{module}"] = Binding("module", path=target)
                else:
                    out[root] = Binding("external", package=root)
            return
        target = self.py_modules.get(module)
        if imp.star:
            if target:
                pf = self.files.get(target)
                names = (pf.exports if pf and pf.exports else list(self.top.get(target, {})))
                for n in names:
                    out.setdefault(n, Binding("symbol", path=target, name=n))
            return
        for name, alias in imp.names:
            sub = self.py_modules.get(f"{module}.{name}" if module else name)
            if sub:
                out[alias] = Binding("module", path=sub)
            elif target:
                out[alias] = Binding("symbol", path=target, name=name)
            else:
                out[alias] = Binding("external", package=(module or name).split(".")[0], name=name)

    def _ts_resolve_spec(self, path: str, spec: str) -> str | None:
        if spec.startswith("."):
            base = _join(str(PurePosixPath(path).parent), spec)
            return self._ts_file(base)
        for cfg_dir, cfg in sorted(self.tsconfigs.items(), key=lambda kv: -len(kv[0])):
            if cfg_dir and not path.startswith(cfg_dir + "/"):
                continue
            for pattern, targets in cfg.paths.items():
                if pattern.endswith("*"):
                    prefix = pattern[:-1]
                    if not spec.startswith(prefix):
                        continue
                    rest = spec[len(prefix):]
                    for t in targets:
                        hit = self._ts_file(_join(cfg.base_dir, t.replace("*", rest)))
                        if hit:
                            return hit
                elif spec == pattern:
                    for t in targets:
                        hit = self._ts_file(_join(cfg.base_dir, t))
                        if hit:
                            return hit
            if cfg.has_base_url:
                hit = self._ts_file(_join(cfg.base_dir, spec))
                if hit:
                    return hit
        return None

    def _ts_file(self, base: str) -> str | None:
        if base in self.all_paths and base in self.files:
            return base
        for ext in _TS_EXTS:
            cand = base + ext
            if cand in self.all_paths:
                return cand
        return None

    def _ts_import(self, path: str, imp: ImportRec, out: dict[str, Binding]) -> None:
        target = self._ts_resolve_spec(path, imp.module)
        if target is None:
            spec = imp.module
            pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
            pkg = pkg.removeprefix("node:")
            if imp.alias:
                out[imp.alias] = Binding("external", package=pkg)
            for _name, alias in imp.names:
                out[alias] = Binding("external", package=pkg)
            out.setdefault(f"__ext__{pkg}", Binding("external", package=pkg))
            return
        if imp.alias:
            out[imp.alias] = Binding("module", path=target, dynamic=imp.dynamic)
        for name, alias in imp.names:
            if name == "default":
                pf = self.files.get(target)
                name = (pf.default_export if pf and pf.default_export else "default")
            out[alias] = Binding("symbol", path=target, name=name, dynamic=imp.dynamic)
        if imp.star and not imp.alias:
            for n in self.top.get(target, {}):
                out.setdefault(f"__star__{n}", Binding("symbol", path=target, name=n))
        out.setdefault(f"__file__{target}", Binding("module", path=target, dynamic=imp.dynamic))

    def _go_import(self, imp: ImportRec, out: dict[str, Binding]) -> None:
        alias = imp.alias or imp.module.rsplit("/", 1)[-1]
        if self.go_module and (imp.module == self.go_module or imp.module.startswith(self.go_module + "/")):
            rel = imp.module[len(self.go_module):].lstrip("/") or "."
            paths = tuple(p for p in self.dir_files.get(rel, []) if p.endswith(".go"))
            if paths:
                out[alias] = Binding("module", paths=paths, path=paths[0])
                return
        out[alias] = Binding("external", package=imp.module)

    def _java_import(self, imp: ImportRec, out: dict[str, Binding]) -> None:
        rel = imp.module.replace(".", "/")
        if imp.star:
            paths = tuple(p for p in self.files if p.endswith(".java") and str(PurePosixPath(p).parent).endswith(rel))
            for p in paths:
                for n, ref in self.top.get(p, {}).items():
                    if ref.sym.kind == "class":
                        out.setdefault(n, Binding("symbol", path=p, name=n))
            return
        cands = [p for p in self.files if p.endswith(rel + ".java")]
        name = imp.module.rsplit(".", 1)[-1]
        if len(cands) == 1:
            out[name] = Binding("symbol", path=cands[0], name=name)
        else:
            out[name] = Binding("external", package=imp.module.rsplit(".", 1)[0])

    def _rust_module_file(self, path: str, segments: list[str]) -> str | None:
        """Resolve `crate::a::b` / `super::x` / `self::x` to a module file."""
        if not segments:
            return path
        cur = path
        segs = list(segments)
        if segs[0] == "crate":
            root_dir = None
            p = PurePosixPath(path)
            for parent in [p.parent, *p.parents]:
                for name in ("lib.rs", "main.rs"):
                    cand = str(parent / name) if str(parent) != "." else name
                    if cand in self.all_paths:
                        root_dir = cand
                        break
                if root_dir:
                    break
            if root_dir is None:
                return None
            cur = root_dir
            segs = segs[1:]
        elif segs[0] == "self":
            segs = segs[1:]
        elif segs[0] == "super":
            while segs and segs[0] == "super":
                cur = self._rust_parent(cur) or cur
                segs = segs[1:]
        for seg in segs:
            nxt = self._rust_child(cur, seg)
            if nxt is None:
                return None
            cur = nxt
        return cur

    def _rust_dir(self, path: str) -> str:
        p = PurePosixPath(path)
        if p.name in ("mod.rs", "lib.rs", "main.rs"):
            return str(p.parent)
        return str(p.with_suffix(""))

    def _rust_child(self, path: str, name: str) -> str | None:
        d = self._rust_dir(path)
        for cand in (f"{d}/{name}.rs", f"{d}/{name}/mod.rs"):
            cand = cand.lstrip("./") if cand.startswith("./") else cand
            if cand in self.all_paths:
                return cand
        return None

    def _rust_parent(self, path: str) -> str | None:
        p = PurePosixPath(path)
        d = p.parent
        if p.name == "mod.rs":
            d = d.parent
        for name in ("mod.rs", "lib.rs", "main.rs"):
            cand = str(d / name)
            if cand in self.all_paths:
                return cand
        cand = str(d) + ".rs"
        return cand if cand in self.all_paths else None

    def _rust_import(self, path: str, imp: ImportRec, out: dict[str, Binding]) -> None:
        segs = [s for s in imp.module.split("::") if s]
        if not segs or segs[0] not in ("crate", "self", "super"):
            pkg = segs[0] if segs else imp.module
            for _n, alias in imp.names:
                out[alias] = Binding("external", package=pkg)
            return
        target = self._rust_module_file(path, segs)
        for name, alias in imp.names:
            if target is None:
                continue
            sub = self._rust_child(target, name)
            if sub:
                out[alias] = Binding("module", path=sub)
            else:
                out[alias] = Binding("symbol", path=target, name=name)
        if imp.star and target:
            for n in self.top.get(target, {}):
                out.setdefault(n, Binding("symbol", path=target, name=n))

    def _clj_import(self, imp: ImportRec, out: dict[str, Binding]) -> None:
        target = self.clj_ns.get(imp.module)
        if imp.alias:
            out[imp.alias] = Binding("module", path=target) if target else Binding("external", package=imp.module)
        if target is None:
            out.setdefault(imp.module, Binding("external", package=imp.module))
        else:
            out.setdefault(imp.module, Binding("module", path=target))
        for name, alias in imp.names:
            out[alias] = Binding("symbol", path=target, name=name) if target else Binding(
                "external", package=imp.module)

    # Lookups
    def lookup_in_file(self, path: str, dotted: list[str]) -> SymRef | None:
        """`name`, `Class.method` (or `Type::method`) inside one file."""
        if not dotted:
            return None
        ref = self.top.get(path, {}).get(dotted[0])
        for part in dotted[1:]:
            if ref is None:
                return None
            ref = self.methods.get(ref.id, {}).get(part) or self.children.get(ref.id, {}).get(part)
        return ref

    def class_method(self, class_id: str, name: str, depth: int = 0) -> SymRef | None:
        hit = self.methods.get(class_id, {}).get(name)
        if hit is not None or depth > 5:
            return hit
        for base_id, _conf in self.bases.get(class_id, []):
            hit = self.class_method(base_id, name, depth + 1)
            if hit is not None:
                return hit
        return None

    def _resolve_bases(self, ref: SymRef) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for base in ref.sym.bases:
            name = re.split(r"[<(\[]", base, maxsplit=1)[0].strip()
            parts = [p for p in re.split(r"\.|::", name) if p]
            if not parts:
                continue
            hit, conf = self._resolve_parts(ref, parts, want="class")
            if hit is not None and hit.id != ref.id:
                out.append((hit.id, conf))
        return out

    def _cap(self, ref: SymRef, conf: float) -> float:
        return min(conf, TIER2_CAP) if ref.tier == 2 else conf

    def _resolve_parts(self, caller: SymRef, parts: list[str], want: str = "any") -> tuple[SymRef | None, float]:
        """Resolve a name path for bases (no call context)."""
        path = caller.path
        local = self.lookup_in_file(path, parts)
        if local is not None and (want == "any" or local.sym.kind == want):
            return local, self._cap(caller, CONF["local"])
        b = self.bindings.get(path, {}).get(parts[0])
        if b is not None and b.kind != "external":
            hit = self._via_binding(b, parts[1:])
            if hit is not None:
                return hit, self._cap(caller, CONF["dynamic" if b.dynamic else "import"])
        if len(parts) > 1:
            hits = self.by_qual.get((caller.family, ".".join(parts)), []) + self.by_qual.get(
                (caller.family, "::".join(parts)), [])
            hits = [h for h in hits if want == "any" or h.sym.kind == want]
            if len(hits) == 1:
                return hits[0], self._cap(caller, CONF["project"])
        table = self.cls_by_name if want == "class" else self.fn_by_name
        hits = table.get((caller.family, parts[-1]), [])
        if len(hits) == 1:
            return hits[0], self._cap(caller, CONF["name_only"])
        return None, 0.0

    def _via_binding(self, b: Binding, rest: list[str]) -> SymRef | None:
        if b.kind == "symbol" and b.path:
            return self.lookup_in_file(b.path, [b.name or "", *rest])
        if b.kind == "module":
            if not rest:
                return None
            paths = b.paths or ((b.path,) if b.path else ())
            for p in paths:
                hit = self.lookup_in_file(p, rest)
                if hit is not None:
                    return hit
        return None


@dataclass
class _Outcome:
    target: SymRef | None
    tier: str  # local, self, import, dynamic, project, name_only, external, unresolved
    conf: float = 0.0


class Resolver:
    def __init__(self, snap: Snapshot) -> None:
        self.snap = snap

    def run(self) -> Resolution:
        res = Resolution()
        snap = self.snap
        for path, binds in snap.bindings.items():
            fid = ids.code_file(snap.repo, path)
            for local, b in binds.items():
                targets = b.paths or ((b.path,) if b.path else ())
                if b.kind in ("module", "symbol"):
                    for t in targets:
                        if t is None or t == path:
                            continue
                        key = (fid, ids.code_file(snap.repo, t))
                        syms, line = res.imports.get(key, ([], 0))
                        name = b.name or (local if not local.startswith("__") else None)
                        if name and name not in syms:
                            syms.append(name)
                        res.imports[key] = (syms, line or self._import_line(path, t))
                elif b.kind == "external" and b.package:
                    pkgs = res.external.setdefault(path, {})
                    sym_set = pkgs.setdefault(b.package, set())
                    if b.name:
                        sym_set.add(b.name)
                    elif not local.startswith("__"):
                        sym_set.add(local)
        for ref in snap.refs.values():
            if ref.sym.kind == "class":
                for base_id, conf in snap.bases.get(ref.id, []):
                    res.inherits[(ref.id, base_id)] = conf
                continue
            unresolved = 0
            for site in ref.sym.calls:
                out = self.resolve(ref, site)
                res.tiers[out.tier] = res.tiers.get(out.tier, 0) + 1
                if out.target is None:
                    if out.tier == "unresolved":
                        unresolved += 1
                    continue
                if out.target.id == ref.id and site.kind != "new" and out.tier == "name_only":
                    continue
                resolution = {"self": "local", "dynamic": "import"}.get(out.tier, out.tier)
                table = res.instantiates if out.target.sym.kind == "class" else res.calls
                key = (ref.id, out.target.id)
                edge = table.get(key)
                if edge is None:
                    table[key] = Edge(resolution, out.conf, [site.line])
                else:
                    edge.lines.append(site.line)
                    if out.conf > edge.confidence:
                        edge.confidence, edge.resolution = out.conf, resolution
            res.unresolved[ref.id] = unresolved
        return res

    def _import_line(self, path: str, target: str) -> int:
        for imp in self.snap.files[path].imports:
            if target.rsplit(".", 1)[0].replace("/", ".").endswith(imp.module.lstrip("./").replace("/", ".")):
                return imp.line
        imps = self.snap.files[path].imports
        return imps[0].line if imps else 0

    # Core
    def resolve(self, caller: SymRef, site: CallSite) -> _Outcome:
        snap = self.snap
        callee = site.callee.strip()
        for prefix in ("await ", "new "):
            callee = callee.removeprefix(prefix)
        callee = re.sub(r"<[^<>()]*>", "", callee)
        fam = caller.family
        lang = snap.files[caller.path].language
        if site.kind == "macro":
            return _Outcome(None, "external")
        receiver_unknown = False
        if lang == "clojure":
            parts = callee.split("/", 1) if "/" in callee and not callee.startswith("/") else [callee]
        else:
            if ")" in callee:
                tail = callee[callee.rfind(")") + 1 :].lstrip(".").lstrip(":")
                if callee.startswith(("super()", "super(")) and lang == "python":
                    parts = ["super", *[p for p in tail.split(".") if p]]
                else:
                    parts = [p for p in re.split(r"\.|::", tail) if p]
                    receiver_unknown = True
            else:
                parts = [p for p in re.split(r"\.|::|->", callee) if p]
        if not parts:
            return _Outcome(None, "external")
        def cap(c: float) -> float:
            return min(c, TIER2_CAP) if caller.tier == 2 else c

        want_class = site.kind == "new"

        if receiver_unknown:
            return self._name_only(caller, parts[-1], want_class, count_missing=False)

        head = parts[0]
        if len(parts) > 1 and head in _BUILTINS.get(fam, frozenset()) and head not in _SELF_NAMES \
                and head != "super" and head not in snap.bindings.get(caller.path, {}):
            return _Outcome(None, "external")  # console.log, Math.max, str.join
        # self / this / super
        if head in _SELF_NAMES or head == "super":
            if len(parts) == 2:
                cls = self._enclosing_class(caller)
                if cls is not None:
                    if head == "super":
                        for base_id, _c in snap.bases.get(cls.id, []):
                            hit = snap.class_method(base_id, parts[1])
                            if hit is not None:
                                return _Outcome(hit, "self", cap(CONF["self"]))
                    else:
                        hit = snap.class_method(cls.id, parts[1])
                        if hit is not None:
                            return _Outcome(hit, "self", cap(CONF["self"]))
            if len(parts) == 1:
                return _Outcome(None, "external")
            return self._name_only(caller, parts[-1], want_class, count_missing=False)

        # local scope chain
        if len(parts) == 1:
            hit = self._local(caller, head)
            if hit is not None:
                return _Outcome(hit, "local", cap(CONF["local"]))
            if lang in ("java", "kotlin", "scala", "swift", "cpp", "ruby", "php"):
                cls = self._enclosing_class(caller)
                if cls is not None:
                    hit = snap.class_method(cls.id, head)
                    if hit is not None:
                        return _Outcome(hit, "self", cap(CONF["self"]))
        else:
            hit = snap.lookup_in_file(caller.path, parts)
            if hit is not None:
                return _Outcome(hit, "local", cap(CONF["local"]))
            if lang in ("go", "java"):
                for p in snap.dir_files.get(str(PurePosixPath(caller.path).parent), []):
                    if p != caller.path and snap.files[p].language == lang:
                        hit = snap.lookup_in_file(p, parts)
                        if hit is not None:
                            return _Outcome(hit, "local", cap(CONF["local"]))
            if lang == "rust" and head not in snap.bindings.get(caller.path, {}):
                mod_file = snap._rust_module_file(caller.path, ["self", head])
                if mod_file and mod_file != caller.path:
                    hit = snap.lookup_in_file(mod_file, parts[1:])
                    if hit is not None:
                        return _Outcome(hit, "import", cap(CONF["import"]))

        # imports
        binds = snap.bindings.get(caller.path, {})
        b = binds.get(head)
        if b is None and lang == "python" and len(parts) > 1:
            for i in range(len(parts) - 1, 0, -1):
                pkg = binds.get("__pkg__" + ".".join(parts[:i]))
                if pkg is not None and pkg.path:
                    hit = snap.lookup_in_file(pkg.path, parts[i:])
                    if hit is not None:
                        return _Outcome(hit, "import", cap(CONF["import"]))
        if b is None and lang in ("typescript", "tsx", "javascript"):
            b = binds.get(f"__star__{head}")
        if b is not None:
            if b.kind == "external":
                return _Outcome(None, "external")
            hit = snap._via_binding(b, parts[1:])
            if hit is None and b.kind == "module" and lang == "python" and len(parts) > 1:
                # `import pkg.sub` then `pkg.sub.fn()`
                for i in range(len(parts) - 1, 0, -1):
                    pkg = binds.get("__pkg__" + ".".join(parts[:i]))
                    if pkg is not None and pkg.path:
                        hit = snap.lookup_in_file(pkg.path, parts[i:])
                        if hit is not None:
                            break
            if hit is not None:
                return _Outcome(hit, "dynamic" if b.dynamic else "import",
                                cap(CONF["dynamic" if b.dynamic else "import"]))
        if len(parts) == 1 and head in _BUILTINS.get(fam, frozenset()):
            return _Outcome(None, "external")
        if len(parts) == 1 and lang == "go" and head in GO_BUILTINS:
            return _Outcome(None, "external")

        # project-wide qualified name
        if len(parts) > 1:
            for qual in (".".join(parts), "::".join(parts), ".".join(parts[-2:]), "::".join(parts[-2:])):
                hits = snap.by_qual.get((fam, qual), [])
                if want_class:
                    hits = [h for h in hits if h.sym.kind == "class"]
                if len(hits) == 1:
                    return _Outcome(hits[0], "project", cap(CONF["project"]))
                if len(hits) > 1:
                    return _Outcome(None, "unresolved")
            return self._name_only(caller, parts[-1], want_class, count_missing=False)
        return self._name_only(caller, head, want_class, count_missing=caller.tier == 1)

    def _name_only(self, caller: SymRef, name: str, want_class: bool, count_missing: bool) -> _Outcome:
        snap = self.snap
        fam = caller.family
        if name in _BUILTINS.get(fam, frozenset()):
            return _Outcome(None, "external")
        fns = snap.fn_by_name.get((fam, name), [])
        classes = snap.cls_by_name.get((fam, name), [])
        hits = classes if want_class else (fns or classes)
        if len(hits) == 1:
            conf = CONF["name_only"]
            return _Outcome(hits[0], "name_only", min(conf, TIER2_CAP) if caller.tier == 2 else conf)
        if len(hits) > 1:
            # Clojure: an unqualified symbol that is neither local nor referred cannot name another
            # namespace's var, so an ambiguous match means a core or macro name (e.g. copies of clojure.core)
            return _Outcome(None, "external" if fam == "clj" else "unresolved")
        return _Outcome(None, "unresolved" if count_missing else "external")

    def _local(self, caller: SymRef, name: str) -> SymRef | None:
        snap = self.snap
        keyed = snap.by_file[caller.path]
        ref: SymRef | None = caller
        while ref is not None:
            if ref.sym.kind == "function":
                hit = snap.children.get(ref.id, {}).get(name)
                if hit is not None:
                    return hit
            ref = keyed.get(ref.sym.parent) if ref.sym.parent else None
        hit = snap.top.get(caller.path, {}).get(name)
        if hit is not None:
            return hit
        lang = snap.files[caller.path].language
        if lang in ("go", "java"):
            for p in snap.dir_files.get(str(PurePosixPath(caller.path).parent), []):
                if p != caller.path and snap.files[p].language == lang:
                    hit = snap.top.get(p, {}).get(name)
                    if hit is not None:
                        return hit
        return None

    def _enclosing_class(self, caller: SymRef) -> SymRef | None:
        snap = self.snap
        keyed = snap.by_file[caller.path]
        ref: SymRef | None = caller
        while ref is not None:
            if ref.sym.kind == "class":
                return ref
            ref = keyed.get(ref.sym.parent) if ref.sym.parent else None
        # Go / Rust methods outside their type
        sym = caller.sym
        if sym.fn_kind == "method":
            sep = "::" if "::" in sym.qualname else "."
            owner = sym.qualname.rsplit(sep, 1)[0].rsplit(sep, 1)[-1]
            for cls in snap.cls_by_name.get((caller.family, owner), []):
                return cls
        return None


def resolve_snapshot(snap: Snapshot) -> Resolution:
    return Resolver(snap).run()


def build_snapshot(repo: str, sources: dict[str, bytes], parsed: dict[str, ParsedFile] | None = None) -> Snapshot:
    """Parse code files (unless `parsed` is given) and read tsconfig and go.mod for import resolution."""
    from actron.connectors.code.parse import parse_file

    files: dict[str, ParsedFile] = dict(parsed or {})
    if parsed is None:
        for path, data in sources.items():
            pf = parse_file(path, data)
            if pf is not None:
                files[path] = pf
    tsconfigs: dict[str, TsPaths] = {}
    go_module: str | None = None
    for path, data in sources.items():
        name = PurePosixPath(path).name
        if name == "tsconfig.json" or (name.startswith("tsconfig") and name.endswith(".json")):
            cfg = read_tsconfig(data.decode("utf-8", "replace"), path)
            folder = str(PurePosixPath(path).parent)
            folder = "" if folder == "." else folder
            if cfg is not None and (name == "tsconfig.json" or folder not in tsconfigs):
                tsconfigs[folder] = cfg
        elif name == "go.mod" and go_module is None:
            m = re.search(r"^module\s+(\S+)", data.decode("utf-8", "replace"), re.MULTILINE)
            if m:
                go_module = m.group(1)
    return Snapshot(repo, files, set(sources), tsconfigs, go_module)
