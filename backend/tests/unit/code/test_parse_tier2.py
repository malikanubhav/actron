"""A-AC-88: each tier-2 language parses; functions and classes come out with correct names and line ranges."""

from __future__ import annotations

import pytest

from actron.connectors.code.parse import parse_file

SAMPLES: dict[str, tuple[str, bytes, dict[str, tuple[int, int]], dict[str, list[str]]]] = {
    "kotlin": ("src/Foo.kt", b"""package a.b
import x.y.Z
class Foo(val x: Int) : Bar() {
    fun greet(name: String): String { return helper(name) }
}
interface Shape { fun area(): Double }
fun helper(n: String): String = n.uppercase()
""", {"Foo": (3, 5), "Foo.greet": (4, 4), "Shape": (6, 6), "Shape.area": (6, 6), "helper": (7, 7)},
        {"Foo.greet": ["helper"]}),
    "ruby": ("lib/foo.rb", b"""module Outer
  class Foo < Bar
    def greet(name)
      helper(name)
    end
    def self.make
      Foo.new
    end
  end
end
def helper(x)
  puts x
end
""", {"Outer": (1, 10), "Outer.Foo": (2, 9), "Outer.Foo.greet": (3, 5), "Outer.Foo.make": (6, 8),
      "helper": (11, 13)}, {"Outer.Foo.greet": ["helper"], "Outer.Foo.make": ["Foo.new"]}),
    "php": ("src/Foo.php", b"""<?php
namespace App;
class Foo extends Bar {
    public function greet($n) { return helper($n) . $this->x(); }
}
interface I { public function x(); }
function helper($n) { return strtoupper($n); }
""", {"Foo": (3, 5), "Foo.greet": (4, 4), "I": (6, 6), "I.x": (6, 6), "helper": (7, 7)},
        {"Foo.greet": ["helper", "this.x"], "helper": ["strtoupper"]}),
    "c": ("src/main.c", b"""#include <stdio.h>
struct point { int x; int y; };
static int helper(int a) { return a + 1; }
int main(void) {
  printf("%d", helper(2));
  return 0;
}
""", {"point": (2, 2), "helper": (3, 3), "main": (4, 7)}, {"main": ["printf", "helper"]}),
    "cpp": ("src/geo.cpp", b"""#include <vector>
namespace geo {
class Shape : public Base {
 public:
  double area() const { return compute(1); }
};
int compute(int a) { return a * 2; }
}
double Shape2::perimeter() { return geo::compute(3); }
""", {"geo.Shape": (3, 6), "geo.Shape.area": (5, 5), "geo.compute": (7, 7), "Shape2.perimeter": (9, 9)},
        {"geo.Shape.area": ["compute"], "Shape2.perimeter": ["geo.compute"]}),
    "scala": ("src/Main.scala", b"""package a
class Foo(x: Int) extends Bar {
  def greet(n: String): String = helper(n)
}
object Main { def main(args: Array[String]): Unit = println(helper("x")) }
trait T { def t(): Int }
def helper(s: String): String = s.toUpperCase
""", {"Foo": (2, 4), "Foo.greet": (3, 3), "Main": (5, 5), "Main.main": (5, 5), "T": (6, 6), "helper": (7, 7)},
        {"Foo.greet": ["helper"], "Main.main": ["println", "helper"]}),
    "swift": ("Sources/Foo.swift", b"""import Foundation
class Foo: Bar {
    func greet(name: String) -> String { return helper(name) }
    init() {}
}
protocol Shape { func area() -> Double }
func helper(_ n: String) -> String { return n.uppercased() }
""", {"Foo": (2, 5), "Foo.greet": (3, 3), "Foo.init": (4, 4), "Shape": (6, 6), "helper": (7, 7)},
        {"Foo.greet": ["helper"], "helper": ["n.uppercased"]}),
    "clojure": ("src/calva/foo.cljs", b"""(ns calva.foo
  (:require [calva.bar :as bar]
            [clojure.string :refer [join]]))

(defn greet
  "Docstring"
  [name]
  (bar/helper name))

(defn- private-fn [x] (greet x))

(defprotocol P (area [this]))
(defrecord R [a b])

(comment
  (defn scratch [] 1))
""", {"greet": (5, 8), "private-fn": (10, 10), "P": (12, 12), "R": (13, 13)},
        {"greet": ["bar/helper"], "private-fn": ["greet"]}),
}


@pytest.mark.parametrize("lang", sorted(SAMPLES))
def test_tier2_symbols(lang: str) -> None:
    """A-AC-88"""
    path, src, expected_ranges, expected_calls = SAMPLES[lang]
    pf = parse_file(path, src)
    assert pf is not None and pf.tier == 2
    got = {s.key: (s.start_line, s.end_line) for s in pf.symbols}
    for key, rng in expected_ranges.items():
        assert got.get(key) == rng, (key, got)
    calls = {s.key: [c.callee for c in s.calls] for s in pf.symbols}
    for key, callees in expected_calls.items():
        assert calls[key] == callees, (key, calls[key])


def test_clojure_ns_requires_and_privacy() -> None:
    """A-AC-88"""
    pf = parse_file("src/calva/foo.cljs", SAMPLES["clojure"][1])
    assert pf is not None
    assert pf.namespace == "calva.foo"
    reqs = {i.module: i for i in pf.imports}
    assert reqs["calva.bar"].alias == "bar"
    assert reqs["clojure.string"].names == [("join", "join")]
    syms = {s.key: s for s in pf.symbols}
    assert syms["greet"].docstring == "Docstring" and syms["greet"].parameters == ["name"]
    assert syms["private-fn"].is_public is False
    assert "scratch" not in syms


def test_clojure_deftest() -> None:
    """A-AC-88, A-AC-30"""
    src = b"(ns calva.foo-test (:require [calva.foo :as foo]))\n(deftest greet-test\n  (is (= 1 (foo/greet 1))))\n"
    pf = parse_file("test/calva/foo_test.clj", src)
    assert pf is not None
    t = pf.symbols[0]
    assert t.key == "greet-test" and t.is_test
    assert [c.callee for c in t.calls] == ["is", "=", "foo/greet"]
