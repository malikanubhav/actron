"""A-AC-30: test detection and TESTS / TESTS_CLASS / TEST_FILE_FOR links (calls and naming), including Mocha
TDD `suite`/`test` and Clojure `deftest`."""

from __future__ import annotations

from textwrap import dedent

from actron.connectors.code.resolve import build_snapshot, resolve_snapshot
from actron.connectors.code.tests_link import is_test_file, link_tests, mark_tests
from actron.graph import ids

REPO = "acme/app"


def _run(files: dict[str, str]):
    snap = build_snapshot(REPO, {p: dedent(s).encode() for p, s in files.items()})
    test_files = mark_tests(snap.files)
    res = resolve_snapshot(snap)
    return snap, link_tests(snap, res, test_files), test_files


def test_test_file_rules() -> None:
    """A-AC-30"""
    assert is_test_file("tests/test_app.py", "python")
    assert is_test_file("pkg/app_test.py", "python")
    assert is_test_file("conftest.py", "python")
    assert not is_test_file("pkg/app.py", "python")
    assert is_test_file("src/a.test.ts", "typescript")
    assert is_test_file("src/a.spec.tsx", "tsx")
    assert is_test_file("src/extension-test/unit/util-test.ts", "typescript")
    assert is_test_file("src/__tests__/x.js", "javascript")
    assert not is_test_file("src/extension.ts", "typescript")
    assert is_test_file("test/calva/foo_test.cljs", "clojure")
    assert is_test_file("src/calva/foo_test.clj", "clojure")
    assert not is_test_file("src/calva/foo.cljs", "clojure")
    assert is_test_file("pkg/a_test.go", "go")
    assert is_test_file("src/test/java/AppTest.java", "java")
    assert is_test_file("spec/foo_spec.rb", "ruby")


def test_python_calls_and_naming() -> None:
    """A-AC-30"""
    files = {
        "app.py": """\
            def make_response(x):
                return x

            def other():
                return 1

            class Client:
                pass
            """,
        "tests/test_app.py": """\
            from app import make_response, other, Client

            def test_other():
                assert other() == 1

            def test_make_response():
                assert True

            class TestClient:
                def test_builds(self):
                    Client()

            def helper():
                return other()
            """,
    }
    _snap, links, test_files = _run(files)
    t = "tests/test_app.py"
    fn = lambda p, q: ids.code_fn(REPO, p, q)  # noqa: E731
    assert links.tests[(fn(t, "test_other"), fn("app.py", "other"))] == ("calls", 0.95)
    assert links.tests[(fn(t, "test_make_response"), fn("app.py", "make_response"))] == ("naming", 0.6)
    assert links.tests_class[(fn(t, "TestClient.test_builds"), ids.code_class(REPO, "app.py", "Client"))][0] == "calls"
    assert not any(a == fn(t, "helper") for a, _ in links.tests)  # helper is not a test
    assert links.test_file_for[(ids.code_file(REPO, t), ids.code_file(REPO, "app.py"))] == ("naming", 0.8)
    assert t in test_files


def test_mocha_tdd_and_bdd() -> None:
    """A-AC-30"""
    files = {
        "src/util.ts": "export function trim(s: string) { return s.trim(); }\nexport function pad(s: string) { return s; }\n",
        "src/extension-test/unit/util-test.ts": """\
            import { trim, pad } from '../../util';
            suite('util', () => {
              test('trims', () => { trim(' a '); });
            });
            describe('pad', () => {
              it('pads', () => { pad('a'); });
            });
            """,
    }
    _snap, links, _ = _run(files)
    t = "src/extension-test/unit/util-test.ts"
    assert (ids.code_fn(REPO, t, "util > trims"), ids.code_fn(REPO, "src/util.ts", "trim")) in links.tests
    assert (ids.code_fn(REPO, t, "pad > pads"), ids.code_fn(REPO, "src/util.ts", "pad")) in links.tests
    assert links.test_file_for[(ids.code_file(REPO, t), ids.code_file(REPO, "src/util.ts"))] == ("naming", 0.8)


def test_clojure_deftest() -> None:
    """A-AC-30"""
    files = {
        "src/calva/foo.cljs": "(ns calva.foo)\n(defn greet [n] n)\n",
        "test/calva/foo_test.cljs": "(ns calva.foo-test (:require [calva.foo :as foo]))\n"
                                    "(deftest greet-test\n  (is (= 1 (foo/greet 1))))\n",
    }
    _snap, links, _ = _run(files)
    key = (ids.code_fn(REPO, "test/calva/foo_test.cljs", "greet-test"), ids.code_fn(REPO, "src/calva/foo.cljs", "greet"))
    assert links.tests[key] == ("calls", 0.6)


def test_test_file_for_by_majority_of_targets() -> None:
    """A-AC-30"""
    files = {
        "lib/core.py": "def a():\n    return 1\n\ndef b():\n    return 2\n",
        "lib/extra.py": "def c():\n    return 3\n",
        "tests/test_things.py": "from lib.core import a, b\nfrom lib.extra import c\n\n"
                                "def test_one():\n    a()\n    b()\n\ndef test_two():\n    a()\n    c()\n",
    }
    _snap, links, _ = _run(files)
    tf = ids.code_file(REPO, "tests/test_things.py")
    assert links.test_file_for == {(tf, ids.code_file(REPO, "lib/core.py")): ("calls", 0.75)}
