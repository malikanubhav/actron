"""Go parsing (spec A, A6.4a)."""

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
    string_value,
    text,
)

_STOP = frozenset({"function_declaration", "method_declaration"})


def _is_exported(name: str) -> bool:
    return bool(name) and name[0].isupper()


def _call(n: Node) -> CallSite | None:
    if n.type == "call_expression":
        fn = field(n, "function")
        if fn is not None:
            return CallSite("".join(text(fn).split()), start_line(n))
    return None


def _params(node: Node | None) -> list[str]:
    out: list[str] = []
    if node is None:
        return out
    for p in named_children(node):
        for c in p.children:
            if c.type == "identifier":
                out.append(text(c))
    return out


def _receiver_type(node: Node | None) -> str:
    if node is None:
        return ""
    for p in named_children(node):
        t = field(p, "type")
        if t is not None:
            raw = text(t).lstrip("*")
            return raw.split("[", 1)[0]
    return ""


def parse_go(path: str, source: bytes) -> ParsedFile:
    root = parse_tree("go", source)
    lines = source_lines(source)
    pf = ParsedFile(path=path, language="go", tier=1, parse_error=bool(root.has_error))
    classes: dict[str, Symbol] = {}
    methods: list[tuple[Symbol, str]] = []
    for node in root.children:
        t = node.type
        if t == "package_clause":
            ident = next((c for c in node.children if c.type == "package_identifier"), None)
            pf.namespace = text(ident) if ident is not None else None
        elif t == "import_declaration":
            for spec in (s for s in _walk_specs(node)):
                p = field(spec, "path")
                name = field(spec, "name")
                module = string_value(p) or ""
                alias = text(name) if name is not None else module.rsplit("/", 1)[-1]
                pf.imports.append(ImportRec(module=module, line=start_line(spec), alias=alias))
        elif t == "type_declaration":
            for spec in named_children(node):
                if spec.type != "type_spec":
                    continue
                tnode = field(spec, "type")
                name_node = field(spec, "name")
                if tnode is None or name_node is None or tnode.type not in ("struct_type", "interface_type"):
                    continue
                first = start_line(node) if len(named_children(node)) == 1 else start_line(spec)
                last = end_line(node) if len(named_children(node)) == 1 else end_line(spec)
                name = text(name_node)
                bases = []
                for fd in collect(tnode, frozenset(), lambda n: n if n.type in ("field_declaration",
                                                                               "type_elem") else None):
                    if field(fd, "name") is None:
                        bases.append(text(fd).lstrip("*"))
                sym = Symbol(kind="class", name=name, qualname=name, start_line=first, end_line=last,
                             body=lines_text(lines, first, last), docstring=leading_comment(lines, first),
                             bases=bases, is_public=_is_exported(name))
                classes[name] = sym
                pf.symbols.append(sym)
        elif t in ("function_declaration", "method_declaration"):
            name_node = field(node, "name")
            body = field(node, "body")
            if name_node is None:
                continue
            name = text(name_node)
            first, last = start_line(node), end_line(node)
            recv = _receiver_type(field(node, "receiver")) if t == "method_declaration" else ""
            sig_end = body.start_byte if body is not None else node.end_byte
            res = field(node, "result")
            sym = Symbol(
                kind="function", name=name, qualname=f"{recv}.{name}" if recv else name, start_line=first,
                end_line=last, body=lines_text(lines, first, last), fn_kind="method" if recv else "function",
                docstring=leading_comment(lines, first),
                signature=" ".join(source[node.start_byte:sig_end].decode("utf-8", "replace").split()),
                parameters=_params(field(node, "parameters")), return_type=text(res) if res is not None else None,
                is_public=_is_exported(name), calls=collect(body, _STOP, _call),
            )
            if recv:
                methods.append((sym, recv))
            pf.symbols.append(sym)
    for sym, recv in methods:
        if recv in classes:
            sym.parent_obj = classes[recv]
    finalize(pf.symbols)
    return pf


def _walk_specs(node: Node) -> list[Node]:
    return collect(node, frozenset(), lambda n: n if n.type == "import_spec" else None)
