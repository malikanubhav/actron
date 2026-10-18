"""Rust parsing (spec A, A6.4a). Methods in `impl` blocks are qualified `Type::method`; inline modules
prefix names with `module::`. Functions with `#[test]` or inside `#[cfg(test)]` modules are tests."""

from __future__ import annotations

from actron.connectors.code.model import CallSite, ImportRec, ParsedFile, Symbol, finalize
from actron.connectors.code.ts_util import (
    Node,
    collect,
    end_line,
    field,
    leading_comment,
    lines_text,
    named_children,
    parse_tree,
    source_lines,
    start_line,
    text,
)

_STOP = frozenset({"function_item", "impl_item", "mod_item", "trait_item"})
CLASS_TYPES = frozenset({"struct_item", "enum_item", "trait_item", "union_item"})


def _call(n: Node) -> CallSite | None:
    if n.type == "call_expression":
        fn = field(n, "function")
        if fn is not None:
            callee = "".join(text(fn).split()).split("::<", 1)[0]
            return CallSite(callee, start_line(n))
    if n.type == "macro_invocation":
        m = field(n, "macro")
        if m is not None:
            return CallSite(text(m), start_line(n), "macro")
    return None


def _type_name(node: Node | None) -> str:
    if node is None:
        return ""
    raw = text(node)
    return raw.split("<", 1)[0].strip().lstrip("&").strip()


def _use_records(node: Node, line: int, prefix: str, out: list[ImportRec]) -> None:
    t = node.type
    if t in ("scoped_identifier", "identifier", "crate", "self", "super"):
        full = f"{prefix}::{text(node)}" if prefix else text(node)
        module, _, name = full.rpartition("::")
        out.append(ImportRec(module=module or full, line=line, names=[(name, name)] if module else []))
    elif t == "use_as_clause":
        path = field(node, "path")
        alias = field(node, "alias")
        full = f"{prefix}::{text(path)}" if prefix else text(path)
        module, _, name = full.rpartition("::")
        out.append(ImportRec(module=module or full, line=line,
                             names=[(name, text(alias) if alias is not None else name)]))
    elif t == "scoped_use_list":
        path = field(node, "path")
        lst = field(node, "list")
        base = text(path) if path is not None else ""
        full = f"{prefix}::{base}" if prefix and base else (base or prefix)
        if lst is not None:
            for item in named_children(lst):
                _use_records(item, line, full, out)
    elif t == "use_list":
        for item in named_children(node):
            _use_records(item, line, prefix, out)
    elif t == "use_wildcard":
        inner = next(iter(named_children(node)), None)
        base = text(inner) if inner is not None else ""
        full = f"{prefix}::{base}" if prefix and base else (base or prefix)
        out.append(ImportRec(module=full, line=line, star=True))


class _RustParser:
    def __init__(self, path: str, source: bytes) -> None:
        self.source = source
        self.lines = source_lines(source)
        self.pf = ParsedFile(path=path, language="rust", tier=1)
        self.classes: dict[str, Symbol] = {}
        self.pending_bases: list[tuple[str, str]] = []
        self.pending_parents: list[tuple[Symbol, str]] = []

    def run(self) -> ParsedFile:
        root = parse_tree("rust", self.source)
        self.pf.parse_error = bool(root.has_error)
        self._items(root, "", False)
        for sym, type_name in self.pending_parents:
            if sym.parent_obj is None and type_name in self.classes:
                sym.parent_obj = self.classes[type_name]
        for type_name, trait in self.pending_bases:
            cls = self.classes.get(type_name)
            if cls is not None and trait not in cls.bases:
                cls.bases.append(trait)
        finalize(self.pf.symbols)
        return self.pf

    def _items(self, container: Node, mod_prefix: str, in_test_mod: bool) -> None:
        attrs: list[str] = []
        attr_start: int | None = None
        for node in container.children:
            if node.type == "attribute_item":
                attrs.append(text(node).lstrip("#").strip("[]"))
                attr_start = attr_start or start_line(node)
                continue
            first = attr_start or start_line(node) if node.is_named else start_line(node)
            self._item(node, mod_prefix, in_test_mod, attrs, first)
            if node.is_named and node.type != "line_comment":
                attrs, attr_start = [], None

    def _item(self, node: Node, mod: str, in_test_mod: bool, attrs: list[str], first: int) -> None:
        t = node.type
        public = any(c.type == "visibility_modifier" for c in node.children)
        if t == "function_item":
            self._function(node, mod, None, None, in_test_mod, attrs, first, public)
        elif t in CLASS_TYPES:
            name_node = field(node, "name")
            if name_node is None:
                return
            name = text(name_node)
            last = end_line(node)
            sym = Symbol(kind="class", name=name, qualname=f"{mod}{name}", start_line=first, end_line=last,
                         body=lines_text(self.lines, first, last), docstring=leading_comment(self.lines, first),
                         decorators=list(attrs), is_public=public)
            self.pf.symbols.append(sym)
            self.classes[name] = sym
            if t == "trait_item":
                body = field(node, "body")
                if body is not None:
                    self._impl_body(body, f"{mod}{name}", sym, in_test_mod)
        elif t == "impl_item":
            type_name = _type_name(field(node, "type"))
            trait = field(node, "trait")
            if trait is not None:
                self.pending_bases.append((type_name, _type_name(trait)))
            body = field(node, "body")
            if body is not None:
                self._impl_body(body, f"{mod}{type_name}", None, in_test_mod)
        elif t == "mod_item":
            name_node = field(node, "name")
            body = field(node, "body")
            if body is not None and name_node is not None:
                is_test_mod = in_test_mod or any(a.replace(" ", "") == "cfg(test)" for a in attrs)
                self._items(body, f"{mod}{text(name_node)}::", is_test_mod)
        elif t == "use_declaration":
            arg = field(node, "argument")
            if arg is not None:
                _use_records(arg, start_line(node), "", self.pf.imports)

    def _impl_body(self, body: Node, owner: str, cls: Symbol | None, in_test_mod: bool) -> None:
        attrs: list[str] = []
        attr_start: int | None = None
        for node in body.children:
            if node.type == "attribute_item":
                attrs.append(text(node).lstrip("#").strip("[]"))
                attr_start = attr_start or start_line(node)
                continue
            if node.type == "function_item":
                public = any(c.type == "visibility_modifier" for c in node.children)
                sym = self._function(node, "", owner, cls, in_test_mod, attrs, attr_start or start_line(node), public)
                if sym is not None and cls is None:
                    self.pending_parents.append((sym, owner.rsplit("::", 1)[-1]))
            if node.is_named and node.type != "line_comment":
                attrs, attr_start = [], None

    def _function(self, node: Node, mod: str, owner: str | None, parent: Symbol | None, in_test_mod: bool,
                  attrs: list[str], first: int, public: bool) -> Symbol | None:
        name_node = field(node, "name")
        body = field(node, "body")
        if name_node is None:
            return None
        name = text(name_node)
        last = end_line(node)
        params: list[str] = []
        pnode = field(node, "parameters")
        if pnode is not None:
            for p in named_children(pnode):
                pat = field(p, "pattern")
                params.append(text(pat) if pat is not None else text(p))
        rt = field(node, "return_type")
        sig_end = body.start_byte if body is not None else node.end_byte
        sym = Symbol(
            kind="function", name=name, qualname=f"{owner}::{name}" if owner else f"{mod}{name}",
            start_line=first, end_line=last, body=lines_text(self.lines, first, last),
            fn_kind="method" if owner else "function", docstring=leading_comment(self.lines, first),
            signature=" ".join(self.source[node.start_byte:sig_end].decode("utf-8", "replace").split()),
            parameters=params, return_type=text(rt) if rt is not None else None, decorators=list(attrs),
            is_async=any(c.type == "function_modifiers" and "async" in text(c) for c in node.children),
            is_public=public, is_test=in_test_mod or any(a.strip() == "test" or a.endswith("::test") for a in attrs),
            parent_obj=parent, calls=collect(body, _STOP, _call),
        )
        self.pf.symbols.append(sym)
        return sym


def parse_rust(path: str, source: bytes) -> ParsedFile:
    return _RustParser(path, source).run()
