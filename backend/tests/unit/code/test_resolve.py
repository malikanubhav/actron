"""A-AC-29: call resolution tiers and confidences; ambiguous name-only calls create no edge and count as
unresolved. A-AC-88: tier-2 calls create local or name_only edges with confidence <= 0.6."""

from __future__ import annotations

from textwrap import dedent

from actron.connectors.code.resolve import build_snapshot, resolve_snapshot
from actron.graph import ids

REPO = "acme/app"


def fn(path: str, qual: str, dup: int = 1) -> str:
    return ids.code_fn(REPO, path, qual, dup)


def cls(path: str, qual: str) -> str:
    return ids.code_class(REPO, path, qual)


def _resolve(files: dict[str, str]):
    snap = build_snapshot(REPO, {p: dedent(s).encode() for p, s in files.items()})
    return snap, resolve_snapshot(snap)


PY = {
    "pkg/__init__.py": "",
    "pkg/util.py": """\
        def helper(x):
            return x

        def dup_name():
            return 1

        class Base:
            def shared(self):
                return 1
        """,
    "pkg/other.py": """\
        def dup_name():
            return 2

        def only_here():
            return 3
        """,
    "pkg/app.py": """\
        import pkg.util as u
        from pkg.util import helper, Base
        from .other import only_here as oh

        def top():
            def inner():
                return 1
            inner()
            helper(1)
            u.helper(2)
            oh()
            Base.shared(None)
            dup_name()
            unknown_thing()
            len([])
            return Service()

        class Service(Base):
            def run(self):
                self.shared()
                self.local()
                return top()

            def local(self):
                return super().shared()
        """,
}


def test_python_tiers_and_confidences() -> None:
    """A-AC-29"""
    _snap, res = _resolve(PY)
    calls = {(a, b): e for (a, b), e in res.calls.items()}
    top = fn("pkg/app.py", "top")
    assert calls[(top, fn("pkg/app.py", "top.inner"))].resolution == "local"
    assert calls[(top, fn("pkg/app.py", "top.inner"))].confidence == 1.0
    e = calls[(top, fn("pkg/util.py", "helper"))]
    assert (e.resolution, e.confidence, e.count) == ("import", 0.95, 2)
    assert calls[(top, fn("pkg/other.py", "only_here"))].resolution == "import"
    assert calls[(top, fn("pkg/util.py", "Base.shared"))].resolution == "import"
    run = fn("pkg/app.py", "Service.run")
    e = calls[(run, fn("pkg/util.py", "Base.shared"))]
    assert (e.resolution, e.confidence) == ("local", 0.95)  # self tier, inherited method
    assert calls[(run, fn("pkg/app.py", "Service.local"))].confidence == 0.95
    assert calls[(run, top)].resolution == "local"
    assert calls[(fn("pkg/app.py", "Service.local"), fn("pkg/util.py", "Base.shared"))].confidence == 0.95
    # ambiguous name-only call: no edge, counted; unknown bare name: counted; builtin: ignored
    assert not any(b.endswith("::dup_name") for (a, b) in calls if a == top)
    assert res.unresolved[top] == 2
    # class call is an instantiation
    assert (top, cls("pkg/app.py", "Service")) in res.instantiates
    # inheritance inside the repo
    assert res.inherits[(cls("pkg/app.py", "Service"), cls("pkg/util.py", "Base"))] == 0.95


def test_project_and_name_only_tiers() -> None:
    """A-AC-29"""
    files = {
        "a.py": """\
            class Engine:
                def start(self):
                    return 1
            def unique_fn():
                return 2
            """,
        "b.py": """\
            def caller(e):
                Engine.start(e)
                obj.unique_fn()
            """,
    }
    _snap, res = _resolve(files)
    c = fn("b.py", "caller")
    e = res.calls[(c, fn("a.py", "Engine.start"))]
    assert (e.resolution, e.confidence) == ("project", 0.7)
    e = res.calls[(c, fn("a.py", "unique_fn"))]
    assert (e.resolution, e.confidence) == ("name_only", 0.4)


def test_typescript_imports_and_tsconfig_paths() -> None:
    """A-AC-29, A-AC-27"""
    files = {
        "tsconfig.json": """\
            {
              // comment
              "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]},},
            }
            """,
        "src/lib/util.ts": "export function helper() { return 1; }\nexport default function main() {}\n",
        "src/lib/index.ts": "export class Widget { draw() { return 1; } }\n",
        "src/app.ts": """\
            import main, { helper as h } from './lib/util';
            import * as lib from '@/lib';
            import * as vscode from 'vscode';
            export function run() {
              h();
              main();
              const w = new lib.Widget();
              vscode.window.show();
              return lib.Widget;
            }
            """,
    }
    _snap, res = _resolve(files)
    run = fn("src/app.ts", "run")
    assert res.calls[(run, fn("src/lib/util.ts", "helper"))].resolution == "import"
    assert (run, fn("src/lib/util.ts", "main")) in res.calls
    assert res.instantiates[(run, cls("src/lib/index.ts", "Widget"))].confidence == 0.95
    assert res.unresolved[run] == 0
    file_imports = {(a.rsplit(":", 1)[1], b.rsplit(":", 1)[1]) for a, b in res.imports}
    assert ("src/app.ts", "src/lib/util.ts") in file_imports
    assert ("src/app.ts", "src/lib/index.ts") in file_imports
    assert "vscode" in res.external["src/app.ts"]


def test_go_java_rust_resolution() -> None:
    """A-AC-87, A-AC-29"""
    files = {
        "go.mod": "module example.com/mod\n",
        "mathx/mul.go": "package mathx\n\nfunc Mul(a, b float64) float64 { return a * b }\n",
        "shapes/rect.go": """\
            package shapes

            import m "example.com/mod/mathx"

            type Rect struct{ W float64 }

            func (r *Rect) Area() float64 { return m.Mul(r.W, r.W) }
            """,
        "shapes/new.go": "package shapes\n\nfunc NewRect() *Rect { r := &Rect{}; r.Area(); return r }\n",
        "src/main/java/com/ex/util/MathX.java": "package com.ex.util;\npublic class MathX { public static int mul(int a) { return a; } }\n",
        "src/main/java/com/ex/App.java": """\
            package com.ex;
            import com.ex.util.MathX;
            public class App {
              int go() { return MathX.mul(helper()); }
              int helper() { return new App().go(); }
            }
            """,
        "src/lib.rs": "mod helpers;\npub fn top() { helpers::add(1); }\n",
        "src/helpers.rs": "pub fn add(a: i32) -> i32 { a }\n",
    }
    _snap, res = _resolve(files)
    area = fn("shapes/rect.go", "Rect.Area")
    assert res.calls[(area, fn("mathx/mul.go", "Mul"))].resolution == "import"
    newr = fn("shapes/new.go", "NewRect")
    assert res.calls[(newr, area)].resolution == "name_only"
    go_ = fn("src/main/java/com/ex/App.java", "App.go")
    assert res.calls[(go_, fn("src/main/java/com/ex/util/MathX.java", "MathX.mul"))].resolution == "import"
    assert res.calls[(go_, fn("src/main/java/com/ex/App.java", "App.helper"))].confidence == 0.95
    assert (fn("src/main/java/com/ex/App.java", "App.helper"), cls("src/main/java/com/ex/App.java", "App")) in res.instantiates
    assert res.calls[(fn("src/lib.rs", "top"), fn("src/helpers.rs", "add"))].resolution == "import"


def test_tier2_confidence_cap_and_clojure_alias() -> None:
    """A-AC-88"""
    files = {
        "src/calva/bar.cljs": "(ns calva.bar)\n(defn helper [x] x)\n(defn twice [x] (helper (helper x)))\n",
        "src/calva/foo.cljs": "(ns calva.foo (:require [calva.bar :as bar]))\n(defn greet [n] (bar/helper n) (twice n))\n",
        "lib/foo.rb": "def helper(x)\n  x\nend\ndef caller\n  helper(1)\nend\n",
    }
    _snap, res = _resolve(files)
    edges = res.calls
    assert edges[(fn("src/calva/bar.cljs", "twice"), fn("src/calva/bar.cljs", "helper"))].confidence == 0.6
    assert edges[(fn("src/calva/bar.cljs", "twice"), fn("src/calva/bar.cljs", "helper"))].count == 2
    greet = fn("src/calva/foo.cljs", "greet")
    assert edges[(greet, fn("src/calva/bar.cljs", "helper"))].confidence == 0.6
    e = edges[(greet, fn("src/calva/bar.cljs", "twice"))]
    assert (e.resolution, e.confidence) == ("name_only", 0.4)
    assert edges[(fn("lib/foo.rb", "caller"), fn("lib/foo.rb", "helper"))].resolution == "local"
    assert all(e.confidence <= 0.6 for (a, _b), e in edges.items() if a.endswith((".cljs::greet", ".rb::caller")))
