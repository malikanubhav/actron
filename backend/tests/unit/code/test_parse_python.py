"""A-AC-26: Python parsing (functions, async, methods, __init__, properties, nested, decorators,
multiple bases, conditional duplicates, lambdas, __all__, every import form, relative imports)."""

from __future__ import annotations

from textwrap import dedent

from actron.connectors.code.parse_python import parse_python

SRC = dedent(
    '''\
    """Module docstring."""
    import os
    import a.b as ab
    from pkg.mod import helper, other as oth
    from . import sibling
    from ..up import *
    from .local import thing

    __all__ = ["top", "Service"]


    def top(x, *args, y=1, **kwargs) -> int:
        """Top doc."""
        helper(x)
        return oth.run(x)


    async def fetch(url: str) -> bytes:
        return await client.get(url)


    @decorator(with_args=True)
    class Service(Base, mixins.Mixin, metaclass=Meta):
        """Service doc."""

        def __init__(self, a):
            self.a = a

        @property
        def value(self):
            return self._compute()

        @value.setter
        def value(self, v):
            self._v = v

        def _compute(self):
            def inner(z):
                return top(z)
            square = lambda q: q * q
            return inner(square(2))


    if os.name == "nt":
        def plat():
            return 1
    else:
        def plat():
            return 2
    '''
)


def _by_key(pf):
    return {s.key: s for s in pf.symbols}


def test_functions_and_kinds() -> None:
    """A-AC-26"""
    pf = parse_python("pkg/service.py", SRC.encode())
    syms = _by_key(pf)
    assert set(syms) == {
        "top", "fetch", "Service", "Service.__init__", "Service.value", "Service.value~2",
        "Service._compute", "Service._compute.inner", "plat", "plat~2",
    }
    assert syms["top"].fn_kind == "function"
    assert syms["fetch"].is_async is True and syms["fetch"].return_type == "bytes"
    assert syms["Service.__init__"].fn_kind == "constructor"
    assert syms["Service.value"].fn_kind == "property"
    assert syms["Service.value~2"].fn_kind == "property"
    assert syms["Service._compute"].fn_kind == "method"
    assert syms["Service._compute"].is_public is False
    assert syms["Service.__init__"].is_public is True
    assert syms["Service._compute.inner"].fn_kind == "nested"
    assert syms["Service._compute.inner"].parent == "Service._compute"
    assert syms["Service.__init__"].parent == "Service"


def test_line_ranges_and_bodies() -> None:
    """A-AC-26"""
    pf = parse_python("pkg/service.py", SRC.encode())
    syms = _by_key(pf)
    top = syms["top"]
    assert (top.start_line, top.end_line) == (12, 15)
    assert top.body.startswith("def top(") and top.body.endswith("return oth.run(x)")
    svc = syms["Service"]
    assert svc.start_line == 22  # decorator line
    assert svc.decorators == ["decorator(with_args=True)"]
    assert svc.bases == ["Base", "mixins.Mixin"]
    assert svc.docstring == "Service doc."
    assert top.docstring == "Top doc."
    assert top.parameters == ["x", "*args", "y", "**kwargs"]
    assert top.signature == "def top(x, *args, y=1, **kwargs) -> int"
    assert syms["plat"].start_line < syms["plat~2"].start_line


def test_calls_owned_by_innermost_function() -> None:
    """A-AC-26"""
    pf = parse_python("pkg/service.py", SRC.encode())
    syms = _by_key(pf)
    assert [c.callee for c in syms["top"].calls] == ["helper", "oth.run"]
    assert [c.callee for c in syms["Service._compute"].calls] == ["inner", "square"]
    assert [c.callee for c in syms["Service._compute.inner"].calls] == ["top"]
    assert [c.callee for c in syms["Service.value"].calls] == ["self._compute"]
    # lambdas are not functions
    assert not any(s.name == "square" for s in pf.symbols)


def test_imports_and_all() -> None:
    """A-AC-26"""
    pf = parse_python("pkg/service.py", SRC.encode())
    assert pf.exports == ["top", "Service"]
    by_mod = {(i.module, i.level): i for i in pf.imports}
    assert by_mod[("os", 0)].alias is None
    assert by_mod[("a.b", 0)].alias == "ab"
    assert by_mod[("pkg.mod", 0)].names == [("helper", "helper"), ("other", "oth")]
    assert by_mod[("", 1)].names == [("sibling", "sibling")]
    assert by_mod[("up", 2)].star is True
    assert by_mod[("local", 1)].names == [("thing", "thing")]


def test_super_call_text() -> None:
    """A-AC-26"""
    src = b"class A(B):\n    def run(self):\n        return super().run()\n"
    pf = parse_python("a.py", src)
    run = _by_key(pf)["A.run"]
    assert "super().run" in [c.callee for c in run.calls]


def test_ids_stable_when_lines_inserted() -> None:
    """A-AC-25"""
    a = parse_python("m.py", b"def f():\n    return 1\n")
    b = parse_python("m.py", b"\n\n# comment\n\ndef f():\n    return 1\n")
    assert [s.key for s in a.symbols] == [s.key for s in b.symbols] == ["f"]
    assert a.symbols[0].content_hash == b.symbols[0].content_hash
