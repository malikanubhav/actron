"""A-AC-27: TypeScript/TSX/JavaScript parsing (classes, abstract classes, interfaces, methods, exported and
non-exported functions, arrow functions, default exports, every import form, `new`, describe/it tests)."""

from __future__ import annotations

from textwrap import dedent

from actron.connectors.code.parse_typescript import parse_typescript

SRC = dedent(
    """\
    import x from 'm';
    import {a as b, c} from './c';
    import * as ns from '@/lib/ns';
    export {d} from './d';
    export * from './all';
    const r = require('./r');

    /** Main doc. */
    export default function main(p: number): void {
      helper();
      new Foo(1);
      ns.run(p);
    }

    export abstract class Base<T> extends Parent implements I, J {
      @dec()
      method(a: string, ...rest: any[]): string {
        return this.other();
      }
      constructor(private q: number) {
        super();
      }
      get value(): number { return 1; }
      private hidden(): void {}
      handler = (e: E) => { this.method('x'); };
    }

    interface I extends K {
      m(): void;
    }

    export const handler = async (ev: E) => {
      await import('./lazy');
      const inner = () => helper();
      return inner();
    };

    function helper() { return 1; }
    let fe = function named() { return helper(); };
    type Alias = string;
    """
)

TEST_SRC = dedent(
    """\
    import { main } from '../src/main';
    describe('main', () => {
      beforeEach(() => { setup(); });
      it('works', () => {
        expect(main(1)).toBe(1);
      });
      describe('nested', () => {
        it.only('also works', async () => { await main(2); });
      });
    });
    suite('tdd', () => {
      test('uses test', () => { main(3); });
    });
    """
)


def _by_key(pf):
    return {s.key: s for s in pf.symbols}


def test_symbols_and_kinds() -> None:
    """A-AC-27"""
    pf = parse_typescript("src/main.ts", SRC.encode())
    syms = _by_key(pf)
    assert set(syms) == {
        "main", "Base", "Base.method", "Base.constructor", "Base.value", "Base.hidden", "Base.handler",
        "I", "handler", "handler.inner", "helper", "fe",
    }
    assert syms["main"].is_public is True
    assert syms["helper"].is_public is False
    assert syms["handler"].is_async is True and syms["handler"].is_public is True
    assert syms["Base.constructor"].fn_kind == "constructor"
    assert syms["Base.value"].fn_kind == "property"
    assert syms["Base.method"].fn_kind == "method"
    assert syms["Base.method"].decorators == ["dec()"]
    assert syms["Base.hidden"].is_public is False
    assert syms["handler.inner"].fn_kind == "nested"
    assert syms["Base"].bases == ["Parent", "I", "J"]
    assert syms["I"].kind == "class" and syms["I"].bases == ["K"]
    assert "Alias" not in syms


def test_ranges_docs_and_signatures() -> None:
    """A-AC-27"""
    pf = parse_typescript("src/main.ts", SRC.encode())
    syms = _by_key(pf)
    main = syms["main"]
    assert (main.start_line, main.end_line) == (9, 13)
    assert main.docstring == "Main doc."
    assert main.parameters == ["p"]
    assert main.return_type == "void"
    assert main.body.startswith("export default function main")
    assert syms["Base"].start_line == 15


def test_calls_and_new() -> None:
    """A-AC-27"""
    pf = parse_typescript("src/main.ts", SRC.encode())
    syms = _by_key(pf)
    calls = [(c.callee, c.kind) for c in syms["main"].calls]
    assert calls == [("helper", "call"), ("Foo", "new"), ("ns.run", "call")]
    assert [c.callee for c in syms["Base.method"].calls] == ["this.other"]
    assert [c.callee for c in syms["Base.handler"].calls] == ["this.method"]
    assert [c.callee for c in syms["handler"].calls] == ["inner"]
    assert [c.callee for c in syms["handler.inner"].calls] == ["helper"]


def test_imports() -> None:
    """A-AC-27"""
    pf = parse_typescript("src/main.ts", SRC.encode())
    by_mod = {i.module: i for i in pf.imports}
    assert by_mod["m"].names == [("default", "x")]
    assert by_mod["./c"].names == [("a", "b"), ("c", "c")]
    assert by_mod["@/lib/ns"].alias == "ns"
    assert by_mod["./d"].names == [("d", "d")]
    assert by_mod["./all"].star is True
    assert by_mod["./r"].dynamic is True and by_mod["./r"].alias == "r"
    assert by_mod["./lazy"].dynamic is True


def test_describe_it_and_tdd_suites() -> None:
    """A-AC-27, A-AC-30"""
    pf = parse_typescript("test/main.test.ts", TEST_SRC.encode())
    syms = _by_key(pf)
    assert set(syms) == {"main > works", "main > nested > also works", "tdd > uses test"}
    assert all(s.is_test for s in pf.symbols)
    assert [c.callee for c in syms["main > works"].calls] == ["expect(main(1)).toBe", "expect", "main"]
    assert syms["main > nested > also works"].is_async is True


def test_javascript_exports_and_tsx() -> None:
    """A-AC-27"""
    js = b"exports.add = function (a, b) { return a + b; };\nmodule.exports.sub = (a, b) => a - b;\n"
    pf = parse_typescript("lib/math.js", js, "javascript")
    assert {s.key for s in pf.symbols} == {"add", "sub"}
    tsx = b"export function App() { return <div onClick={() => go()}>hi</div>; }\n"
    pf2 = parse_typescript("src/App.tsx", tsx, "tsx")
    assert [s.key for s in pf2.symbols] == ["App"]
    assert [c.callee for c in pf2.symbols[0].calls] == ["go"]
