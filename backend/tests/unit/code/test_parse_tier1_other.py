"""A-AC-87: Go, Java and Rust parsing (classes, functions, methods with receiver or impl qualified names,
imports, calls, tests, Java overloads `~n`, Go exported names, Rust `#[cfg(test)]` modules)."""

from __future__ import annotations

from textwrap import dedent

from actron.connectors.code.parse import parse_file

GO = dedent(
    """\
    package shapes

    import (
    \t"fmt"
    \tm "example.com/mod/mathx"
    )

    // Shape has an area.
    type Shape interface { Area() float64 }

    type Rect struct { W, H float64 }

    func (r *Rect) Area() float64 { return m.Mul(r.W, r.H) }

    func NewRect() *Rect {
    \tfmt.Println("x")
    \treturn &Rect{}
    }

    func helper() {}
    """
)

JAVA = dedent(
    """\
    package com.ex.shapes;

    import com.ex.util.MathX;
    import com.ex.other.*;

    public class Rect extends Base implements Shape {
      public Rect(int w) { super(w); }
      @Override public double area() { return MathX.mul(w, h); }
      double area(int s) { return new Rect(s).area(); }
      static class Inner { void go() {} }
    }

    interface Shape { double area(); }
    enum E { A }
    record P(int x) {}
    """
)

RUST = dedent(
    """\
    use crate::geo::point::Point;
    use super::helpers::{add, sub as minus};

    pub struct Rect { w: f64 }
    pub trait Shape { fn area(&self) -> f64; }

    impl Shape for Rect {
        fn area(&self) -> f64 { add(self.w, 1.0) }
    }

    impl Rect {
        pub fn new() -> Self { println!("x"); Rect { w: 1.0 } }
    }

    pub fn top() { let r = Rect::new(); helpers::add(1, 2); }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn it_works() { top(); }
    }
    """
)


def _keys(pf):
    return {s.key: s for s in pf.symbols}


def test_go() -> None:
    """A-AC-87"""
    pf = parse_file("shapes/shapes.go", GO.encode())
    assert pf is not None
    syms = _keys(pf)
    assert set(syms) == {"Shape", "Rect", "Rect.Area", "NewRect", "helper"}
    assert syms["Rect.Area"].fn_kind == "method" and syms["Rect.Area"].parent == "Rect"
    assert syms["NewRect"].is_public and not syms["helper"].is_public
    assert syms["Shape"].docstring == "Shape has an area."
    assert [c.callee for c in syms["Rect.Area"].calls] == ["m.Mul"]
    assert [c.callee for c in syms["NewRect"].calls] == ["fmt.Println"]
    assert pf.namespace == "shapes"
    assert [(i.module, i.alias) for i in pf.imports] == [("fmt", "fmt"), ("example.com/mod/mathx", "m")]
    assert (syms["NewRect"].start_line, syms["NewRect"].end_line) == (15, 18)


def test_java_overloads_and_calls() -> None:
    """A-AC-87"""
    pf = parse_file("src/main/java/com/ex/shapes/Rect.java", JAVA.encode())
    assert pf is not None
    syms = _keys(pf)
    assert set(syms) == {"Rect", "Rect.Rect", "Rect.area", "Rect.area~2", "Rect.Inner", "Rect.Inner.go",
                         "Shape", "E", "P"}
    assert syms["Rect"].bases == ["Base", "Shape"]
    assert syms["Rect.Rect"].fn_kind == "constructor"
    assert syms["Rect.area"].decorators == ["Override"] and syms["Rect.area"].is_public
    assert not syms["Rect.area~2"].is_public
    assert [(c.callee, c.kind) for c in syms["Rect.area~2"].calls] == [("new Rect(s).area", "call"), ("Rect", "new")]
    assert [c.callee for c in syms["Rect.area"].calls] == ["MathX.mul"]
    assert pf.namespace == "com.ex.shapes"
    assert [(i.module, i.star) for i in pf.imports] == [("com.ex.util.MathX", False), ("com.ex.other", True)]


def test_rust_impl_and_test_module() -> None:
    """A-AC-87"""
    pf = parse_file("src/lib.rs", RUST.encode())
    assert pf is not None
    syms = _keys(pf)
    assert set(syms) == {"Rect", "Shape", "Rect::area", "Rect::new", "top", "tests::it_works"}
    assert syms["Rect"].bases == ["Shape"]
    assert syms["Rect::new"].parent == "Rect" and syms["Rect::new"].fn_kind == "method"
    assert syms["tests::it_works"].is_test and syms["tests::it_works"].decorators == ["test"]
    assert syms["top"].is_public and not syms["Rect::area"].is_public
    assert [(c.callee, c.kind) for c in syms["Rect::new"].calls] == [("println", "macro")]
    assert [c.callee for c in syms["top"].calls] == ["Rect::new", "helpers::add"]
    mods = [(i.module, i.names) for i in pf.imports]
    assert ("crate::geo::point", [("Point", "Point")]) in mods
    assert ("super::helpers", [("add", "add")]) in mods
    assert ("super::helpers", [("sub", "minus")]) in mods
    assert syms["tests::it_works"].start_line == 20  # starts at the #[test] attribute
