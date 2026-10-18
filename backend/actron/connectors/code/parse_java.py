"""Java parsing (spec A, A6.4a). Qualified names are dotted inside the file (`Outer.Inner.method`); the
package is kept on `ParsedFile.namespace` for import resolution. Overloads get `~n` in source order."""

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

CLASS_TYPES = frozenset({"class_declaration", "interface_declaration", "enum_declaration", "record_declaration",
                         "annotation_type_declaration"})
FN_TYPES = frozenset({"method_declaration", "constructor_declaration", "compact_constructor_declaration"})
_STOP = CLASS_TYPES | FN_TYPES


def _call(n: Node) -> CallSite | None:
    if n.type == "method_invocation":
        obj = field(n, "object")
        name = field(n, "name")
        callee = f"{text(obj)}.{text(name)}" if obj is not None else text(name)
        return CallSite(" ".join(callee.split()), start_line(n))
    if n.type == "object_creation_expression":
        typ = field(n, "type")
        if typ is not None:
            return CallSite(text(typ).split("<", 1)[0], start_line(n), "new")
    return None


def _modifiers(node: Node) -> tuple[list[str], set[str]]:
    mods = next((c for c in node.children if c.type == "modifiers"), None)
    annotations: list[str] = []
    words: set[str] = set()
    if mods is not None:
        for c in mods.children:
            if c.type in ("marker_annotation", "annotation"):
                annotations.append(text(c).lstrip("@"))
            else:
                words.add(text(c))
    return annotations, words


class _JavaParser:
    def __init__(self, path: str, source: bytes) -> None:
        self.path = path
        self.source = source
        self.lines = source_lines(source)
        self.pf = ParsedFile(path=path, language="java", tier=1)

    def run(self) -> ParsedFile:
        root = parse_tree("java", self.source)
        self.pf.parse_error = bool(root.has_error)
        for node in root.children:
            if node.type == "package_declaration":
                ident = next((c for c in named_children(node) if c.type in ("scoped_identifier", "identifier")), None)
                self.pf.namespace = text(ident) if ident is not None else None
            elif node.type == "import_declaration":
                ident = next((c for c in named_children(node) if c.type in ("scoped_identifier", "identifier")), None)
                star = any(c.type == "asterisk" for c in node.children)
                module = text(ident) if ident is not None else ""
                rec = ImportRec(module=module, line=start_line(node), star=star)
                if not star and "." in module:
                    rec.names.append((module.rsplit(".", 1)[1], module.rsplit(".", 1)[1]))
                self.pf.imports.append(rec)
            elif node.type in CLASS_TYPES:
                self._class(node, None)
        finalize(self.pf.symbols)
        return self.pf

    def _class(self, node: Node, outer: Symbol | None) -> None:
        name_node = field(node, "name")
        if name_node is None:
            return
        name = text(name_node)
        annotations, words = _modifiers(node)
        bases: list[str] = []
        sup = field(node, "superclass")
        if sup is not None:
            bases.extend(text(c).split("<", 1)[0] for c in named_children(sup))
        for c in node.children:
            if c.type in ("super_interfaces", "extends_interfaces"):
                for tl in named_children(c):
                    bases.extend(text(t).split("<", 1)[0] for t in named_children(tl))
        first, last = start_line(node), end_line(node)
        sym = Symbol(kind="class", name=name, qualname=f"{outer.qualname}.{name}" if outer else name,
                     start_line=first, end_line=last, body=lines_text(self.lines, first, last),
                     docstring=leading_comment(self.lines, first), bases=bases, decorators=annotations,
                     is_public="public" in words, parent_obj=outer)
        self.pf.symbols.append(sym)
        body = field(node, "body")
        if body is None:
            return
        for member in body.children:
            if member.type in CLASS_TYPES:
                self._class(member, sym)
            elif member.type in FN_TYPES:
                self._method(member, sym)
            elif member.type == "enum_body_declarations":
                for m in member.children:
                    if m.type in FN_TYPES:
                        self._method(m, sym)
                    elif m.type in CLASS_TYPES:
                        self._class(m, sym)

    def _method(self, node: Node, cls: Symbol) -> None:
        body = field(node, "body")
        name_node = field(node, "name")
        if body is None or name_node is None:
            return  # abstract or interface method without a body
        name = text(name_node)
        annotations, words = _modifiers(node)
        first, last = start_line(node), end_line(node)
        params: list[str] = []
        fp = field(node, "parameters")
        if fp is not None:
            for p in named_children(fp):
                pn = field(p, "name")
                if pn is not None:
                    params.append(text(pn))
        rt = field(node, "type")
        sym = Symbol(
            kind="function", name=name, qualname=f"{cls.qualname}.{name}", start_line=first, end_line=last,
            body=lines_text(self.lines, first, last),
            fn_kind="constructor" if node.type != "method_declaration" else "method",
            docstring=leading_comment(self.lines, first),
            signature=" ".join(self.source[node.start_byte:body.start_byte].decode("utf-8", "replace").split()),
            parameters=params, return_type=text(rt) if rt is not None else None, decorators=annotations,
            is_public="public" in words, is_test=any(a.split("(", 1)[0].rsplit(".", 1)[-1] == "Test" for a in annotations), parent_obj=cls,
            calls=collect(body, _STOP, _call),
        )
        self.pf.symbols.append(sym)


def parse_java(path: str, source: bytes) -> ParsedFile:
    return _JavaParser(path, source).run()
