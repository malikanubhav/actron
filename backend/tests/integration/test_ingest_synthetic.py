"""Synthetic repos ingested into real FalkorDB: Python (A-AC-26), TypeScript (A-AC-27), Go/Java/Rust (A-AC-87),
tier 2 (A-AC-88), skip rules (A-AC-31), docs (A-AC-32), manifests (A-AC-33), CODEOWNERS (A-AC-34), line coverage
(A-AC-28) and idempotent re-runs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from actron.connectors.code.model import split_lines
from actron.connectors.code.pipeline import CodeIngestReport, ingest_code
from actron.graph import ids
from tests.unit.code.repo_builder import SyntheticRepo

REPO = "acme/synth"


def ingest(graph: Any, repo: SyntheticRepo, tmp: Path, since: str | None = None) -> CodeIngestReport:
    return asyncio.run(ingest_code("synth", REPO, url=repo.url, clone_dir=tmp / "clones", depth=100,
                                   store=graph, since_sha=since))


def fn(path: str, q: str, dup: int = 1) -> str:
    return ids.code_fn(REPO, path, q, dup)


def cls(path: str, q: str) -> str:
    return ids.code_class(REPO, path, q)


def has_link(graph: Any, rel: str, a: str, b: str) -> dict[str, Any] | None:
    rows = graph.query(f"MATCH (x {{id: $a}})-[r:`{rel}`]->(y {{id: $b}}) RETURN properties(r) AS p",
                       {"a": a, "b": b})
    return rows[0]["p"] if rows else None


def node(graph: Any, node_id: str) -> dict[str, Any]:
    got = graph.get_node(node_id)
    assert got is not None, node_id
    return dict(got)


def assert_full_coverage(graph: Any, repo_root: Path) -> None:
    """A-AC-28: every line of every stored text file is inside a function, class, chunk or document section."""
    files = graph.query("MATCH (f:CodeFile) WHERE coalesce(f.isSkipped, false) = false AND "
                        "coalesce(f.deleted, false) = false RETURN f.id AS id, f.path AS path, f.loc AS loc")
    for f in files:
        rows = graph.query(
            "MATCH (n)-[:FUNCTION_DEFINED_IN|CLASS_DEFINED_IN|CHUNK_OF|SECTION_OF]->(f:CodeFile {id: $id}) "
            "WHERE coalesce(n.deleted, false) = false RETURN n.startLine AS s, n.endLine AS e", {"id": f["id"]})
        covered: set[int] = set()
        for r in rows:
            covered.update(range(r["s"], r["e"] + 1))
        n = len(split_lines((repo_root / f["path"]).read_text()))
        assert f["loc"] == n
        missing = set(range(1, n + 1)) - covered
        assert not missing, (f["path"], sorted(missing)[:10])


PY_FILES = {
    "pkg/__init__.py": "",
    "pkg/util.py": """\
        __all__ = ["helper", "Base"]

        def helper(x):
            return x

        class Base:
            def shared(self):
                return helper(1)
        """,
    "pkg/app.py": """\
        import os
        import pkg.util as u
        from pkg.util import helper, Base
        from . import util
        from .util import *

        def deco(arg):
            def wrap(f):
                return f
            return wrap

        @deco(arg=1)
        async def fetch(url):
            return await u.helper(url)

        class Mixin:
            pass

        class App(Base, Mixin):
            def __init__(self):
                self.x = 1

            @property
            def value(self):
                return self._v

            @value.setter
            def value(self, v):
                self._v = v

            def run(self):
                def inner():
                    return helper(2)
                square = lambda q: q * q
                return self.shared() + inner() + square(2)

        if os.name == "nt":
            def plat():
                return 1
        else:
            def plat():
                return 2
        """,
    "tests/test_util.py": """\
        from pkg.util import helper

        def test_helper():
            assert helper(1) == 1
        """,
    "README.md": "# Synth\n\nUses `pkg/util.py` and `App`.\n\n## Usage\nCall `helper`.\n",
    "pyproject.toml": '[project]\nname = "synth"\ndependencies = ["requests>=2"]\n',
    ".github/CODEOWNERS": "* @all\npkg/ @core\n",
}


def test_python_repo(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-26, A-AC-28, A-AC-31, A-AC-32, A-AC-33, A-AC-34"""
    graph = indexed_graph
    r = SyntheticRepo(tmp_path / "src")
    for p, s in PY_FILES.items():
        r.write(p, s)
    r.write_bytes("img/logo.png", b"\x89PNG\x00\x00")
    r.write("package-lock.json", "{}")
    r.commit("init")
    rep = ingest(graph, r, tmp_path)
    app = "pkg/app.py"
    expected = {"deco", "deco.wrap", "fetch", "Mixin", "App", "App.__init__", "App.value", "App.value~2", "App.run",
                "App.run.inner", "plat", "plat~2"}
    got = {x["q"] for x in graph.query(
        "MATCH (n)-[:FUNCTION_DEFINED_IN|CLASS_DEFINED_IN]->(:CodeFile {id: $f}) RETURN "
        "CASE WHEN n.id CONTAINS '~' THEN n.qualifiedName + '~' + split(n.id, '~')[1] ELSE n.qualifiedName END AS q",
        {"f": ids.code_file(REPO, app)})}
    assert got == expected
    fetch = node(graph, fn(app, "fetch"))
    assert fetch["isAsync"] is True and fetch["decorators"] == ["deco(arg=1)"] and fetch["kind"] == "function"
    assert node(graph, fn(app, "App.__init__"))["kind"] == "constructor"
    assert node(graph, fn(app, "App.value~2"))["kind"] == "property"
    assert node(graph, fn(app, "App.run.inner"))["kind"] == "nested"
    assert node(graph, cls(app, "App"))["bases"] == ["Base", "Mixin"]
    assert has_link(graph, "METHOD_OF", fn(app, "App.run"), cls(app, "App"))
    assert has_link(graph, "NESTED_IN", fn(app, "App.run.inner"), fn(app, "App.run"))
    assert has_link(graph, "INHERITS_FROM", cls(app, "App"), cls("pkg/util.py", "Base"))
    assert has_link(graph, "INHERITS_FROM", cls(app, "App"), cls(app, "Mixin"))["confidence"] == 1.0
    e = has_link(graph, "CALLS", fn(app, "App.run"), fn("pkg/util.py", "Base.shared"))
    assert e is not None and e["confidence"] == 0.95 and e["resolution"] == "local"
    e = has_link(graph, "CALLS", fn(app, "fetch"), fn("pkg/util.py", "helper"))
    assert e is not None and e["resolution"] == "import" and e["callSiteLines"] == [14]
    assert has_link(graph, "CALLS", fn(app, "App.run"), fn(app, "App.run.inner"))["resolution"] == "local"
    assert has_link(graph, "IMPORTS", ids.code_file(REPO, app), ids.code_file(REPO, "pkg/util.py"))
    assert has_link(graph, "TESTS", fn("tests/test_util.py", "test_helper"), fn("pkg/util.py", "helper"))
    assert has_link(graph, "TEST_FILE_FOR", ids.code_file(REPO, "tests/test_util.py"),
                    ids.code_file(REPO, "pkg/util.py"))
    logo = node(graph, ids.code_file(REPO, "img/logo.png"))
    assert logo["isSkipped"] is True and logo["skipReason"] == "binary" and "text" not in logo
    assert node(graph, ids.code_file(REPO, "package-lock.json"))["skipReason"] == "lockfile"
    readme = ids.code_doc(REPO, "README.md", "synth")
    assert has_link(graph, "DOC_MENTIONS_FILE", readme, ids.code_file(REPO, "pkg/util.py"))
    assert has_link(graph, "DOC_MENTIONS_CLASS", readme, cls(app, "App"))
    assert has_link(graph, "SUBSECTION_OF", ids.code_doc(REPO, "README.md", "usage"), readme)
    assert has_link(graph, "USES_PACKAGE", ids.code_component(REPO, "."), ids.code_dep("pypi", "requests"))
    rules = {x["f"]: x["p"] for x in graph.query(
        "MATCH (f:CodeFile)-[:MATCHES_OWNER_RULE]->(o:CodeOwnerRule) RETURN f.path AS f, o.pattern AS p")}
    assert rules["pkg/app.py"] == "pkg/" and rules["README.md"] == "*"
    assert rep.counts["CodeRepository"] == 1 and node(graph, ids.code_repo(REPO))["headSha"] == r.head()
    assert_full_coverage(graph, r.root)
    # second run with the same head: nothing new
    rep2 = ingest(graph, r, tmp_path)
    assert rep2.counts == rep.counts and rep2.links == rep.links


TS_FILES = {
    "tsconfig.json": json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}),
    "package.json": json.dumps({"name": "tsapp", "dependencies": {"vscode-languageclient": "^9"},
                                "devDependencies": {"mocha": "^10"}}),
    "src/lib/shapes.ts": """\
        export interface Shape { area(): number; }
        export abstract class Base implements Shape {
          abstract area(): number;
          describe(): string { return `area ${this.area()}`; }
        }
        export class Square extends Base {
          constructor(private s: number) { super(); }
          area(): number { return this.s * this.s; }
        }
        function hidden() { return 1; }
        export default function makeSquare(n: number) { hidden(); return new Square(n); }
        """,
    "src/app.ts": """\
        import makeSquare, { Square as Sq } from './lib/shapes';
        import * as shapes from '@/lib/shapes';
        import { LanguageClient } from 'vscode-languageclient';
        export const run = async () => {
          const a = makeSquare(2);
          const b = new Sq(3);
          return shapes.default ? a.area() + b.area() : 0;
        };
        """,
    "src/extension-test/unit/shapes-test.ts": """\
        import { Square } from '../../lib/shapes';
        describe('Square', () => {
          it('has area', () => { new Square(2).area(); });
        });
        """,
}


def test_typescript_repo(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-27, A-AC-28, A-AC-30"""
    graph = indexed_graph
    r = SyntheticRepo(tmp_path / "src")
    for p, s in TS_FILES.items():
        r.write(p, s)
    r.commit("init")
    ingest(graph, r, tmp_path)
    shapes = "src/lib/shapes.ts"
    assert node(graph, cls(shapes, "Shape"))["bases"] == []
    assert node(graph, cls(shapes, "Square"))["bases"] == ["Base"]
    assert has_link(graph, "INHERITS_FROM", cls(shapes, "Square"), cls(shapes, "Base"))
    assert has_link(graph, "INHERITS_FROM", cls(shapes, "Base"), cls(shapes, "Shape"))
    assert node(graph, fn(shapes, "makeSquare"))["isPublic"] is True
    assert node(graph, fn(shapes, "hidden"))["isPublic"] is False
    assert has_link(graph, "INSTANTIATES", fn(shapes, "makeSquare"), cls(shapes, "Square"))
    run = fn("src/app.ts", "run")
    assert node(graph, run)["isAsync"] is True
    assert has_link(graph, "CALLS", run, fn(shapes, "makeSquare"))["resolution"] == "import"
    assert has_link(graph, "INSTANTIATES", run, cls(shapes, "Square"))
    assert has_link(graph, "IMPORTS", ids.code_file(REPO, "src/app.ts"), ids.code_file(REPO, shapes))
    assert has_link(graph, "IMPORTS_PACKAGE", ids.code_file(REPO, "src/app.ts"),
                    ids.code_dep("npm", "vscode-languageclient"))
    # abstract `area` has no body, so `this.area()` falls to the name-only tier (the single implementation)
    assert has_link(graph, "CALLS", fn(shapes, "Base.describe"), fn(shapes, "Square.area"))["confidence"] == 0.4
    t = fn("src/extension-test/unit/shapes-test.ts", "Square > has area")
    assert node(graph, t)["isTest"] is True
    assert has_link(graph, "TESTS_CLASS", t, cls(shapes, "Square"))
    assert has_link(graph, "TEST_FILE_FOR", ids.code_file(REPO, "src/extension-test/unit/shapes-test.ts"),
                    ids.code_file(REPO, shapes))
    assert_full_coverage(graph, r.root)


TIER1_OTHER = {
    "go.mod": "module example.com/mod\n",
    "mathx/mul.go": "package mathx\n\n// Mul multiplies.\nfunc Mul(a, b float64) float64 { return a * b }\n",
    "shapes/rect.go": "package shapes\n\nimport m \"example.com/mod/mathx\"\n\ntype Rect struct{ W float64 }\n\n"
                      "func (r *Rect) Area() float64 { return m.Mul(r.W, r.W) }\n\nfunc helper() {}\n",
    "shapes/rect_test.go": "package shapes\n\nimport \"testing\"\n\nfunc TestArea(t *testing.T) { helper() }\n",
    "src/main/java/com/ex/App.java": "package com.ex;\n\npublic class App {\n  int go() { return go(1); }\n"
                                     "  int go(int x) { return x; }\n}\n",
    "src/lib.rs": "mod helpers;\n\npub struct Rect { w: f64 }\n\nimpl Rect {\n    pub fn new() -> Self { "
                  "helpers::add(1); Rect { w: 1.0 } }\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n"
                  "    #[test]\n    fn makes() { Rect::new(); }\n}\n",
    "src/helpers.rs": "pub fn add(a: i32) -> i32 { a }\n",
}


def test_go_java_rust_repo(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-87, A-AC-28"""
    graph = indexed_graph
    r = SyntheticRepo(tmp_path / "src")
    for p, s in TIER1_OTHER.items():
        r.write(p, s, raw=True)
    r.commit("init")
    ingest(graph, r, tmp_path)
    assert has_link(graph, "METHOD_OF", fn("shapes/rect.go", "Rect.Area"), cls("shapes/rect.go", "Rect"))
    assert has_link(graph, "CALLS", fn("shapes/rect.go", "Rect.Area"), fn("mathx/mul.go", "Mul"))["resolution"] == "import"
    assert node(graph, fn("mathx/mul.go", "Mul"))["isPublic"] is True
    assert node(graph, fn("shapes/rect.go", "helper"))["isPublic"] is False
    assert node(graph, fn("shapes/rect_test.go", "TestArea"))["isTest"] is True
    assert has_link(graph, "TESTS", fn("shapes/rect_test.go", "TestArea"), fn("shapes/rect.go", "helper"))
    java = "src/main/java/com/ex/App.java"
    assert node(graph, fn(java, "App.go", 2))["parameters"] == ["x"]
    assert has_link(graph, "CALLS", fn(java, "App.go"), fn(java, "App.go"))  # first `go(1)` resolves to `go`
    assert has_link(graph, "METHOD_OF", fn("src/lib.rs", "Rect::new"), cls("src/lib.rs", "Rect"))
    assert has_link(graph, "CALLS", fn("src/lib.rs", "Rect::new"), fn("src/helpers.rs", "add"))
    assert node(graph, fn("src/lib.rs", "tests::makes"))["isTest"] is True
    assert has_link(graph, "TESTS", fn("src/lib.rs", "tests::makes"), fn("src/lib.rs", "Rect::new"))
    assert_full_coverage(graph, r.root)


TIER2 = {
    "src/calva/bar.cljs": "(ns calva.bar)\n\n(defn helper\n  \"Helps.\"\n  [x]\n  x)\n\n(defn twice [x] (helper (helper x)))\n",
    "src/calva/foo.cljs": "(ns calva.foo\n  (:require [calva.bar :as bar]))\n\n(defn greet [n]\n  (bar/helper n))\n",
    "test/calva/foo_test.cljs": "(ns calva.foo-test (:require [calva.foo :as foo]))\n\n"
                                "(deftest greet-test\n  (is (= 1 (foo/greet 1))))\n",
    "lib/foo.rb": "class Foo\n  def greet\n    helper\n  end\nend\n\ndef helper\n  1\nend\n",
    "src/Foo.kt": "class Foo {\n    fun greet(): Int { return helper() }\n}\n\nfun helper(): Int = 1\n",
    "src/foo.php": "<?php\nfunction helper() { return 1; }\nclass Foo { public function greet() { return helper(); } }\n",
    "src/foo.c": "static int helper(void) { return 1; }\nint main(void) { return helper(); }\n",
    "src/foo.cpp": "int helper() { return 1; }\nclass Foo { int greet() { return helper(); } };\n",
    "src/Foo.scala": "object Foo {\n  def greet(): Int = helper()\n}\ndef helper(): Int = 1\n",
    "src/Foo.swift": "class Foo {\n    func greet() -> Int { return helper() }\n}\nfunc helper() -> Int { return 1 }\n",
}


def test_tier2_repo(indexed_graph: Any, tmp_path: Path) -> None:
    """A-AC-88, A-AC-28, A-AC-30"""
    graph = indexed_graph
    r = SyntheticRepo(tmp_path / "src")
    for p, s in TIER2.items():
        r.write(p, s, raw=True)
    r.commit("init")
    ingest(graph, r, tmp_path)
    for path, caller in [("src/calva/bar.cljs", "twice"), ("src/Foo.kt", "Foo.greet"), ("src/foo.php", "Foo.greet"),
                         ("src/foo.c", "main"), ("src/foo.cpp", "Foo.greet"), ("src/Foo.scala", "Foo.greet"),
                         ("src/Foo.swift", "Foo.greet")]:
        e = has_link(graph, "CALLS", fn(path, caller), fn(path, "helper"))
        assert e is not None, path
        assert e["resolution"] in ("local", "name_only") and e["confidence"] <= 0.6
    assert node(graph, fn("src/calva/bar.cljs", "helper"))["docstring"] == "Helps."
    assert has_link(graph, "CALLS", fn("src/calva/foo.cljs", "greet"), fn("src/calva/bar.cljs", "helper"))["confidence"] == 0.6
    assert has_link(graph, "TESTS", fn("test/calva/foo_test.cljs", "greet-test"), fn("src/calva/foo.cljs", "greet"))
    assert has_link(graph, "METHOD_OF", fn("lib/foo.rb", "Foo.greet"), cls("lib/foo.rb", "Foo"))
    assert_full_coverage(graph, r.root)
