"""Python parsing with tree-sitter-python (spec A, A6.3)."""

from __future__ import annotations

from actron.connectors.code.model import (
    CallSite,
    FunctionKind,
    ImportRec,
    ParsedFile,
    Symbol,
    finalize,
)
from actron.connectors.code.ts_util import (
    Node,
    end_line,
    field,
    lines_text,
    named_children,
    parse_tree,
    source_lines,
    start_line,
    string_value,
    text,
)

_COMPOUND = frozenset({
    "if_statement", "elif_clause", "else_clause", "try_statement", "except_clause", "except_group_clause",
    "finally_clause", "with_statement", "for_statement", "while_statement", "block", "match_statement",
    "case_clause",
})
_SCOPE_TYPES = frozenset({"function_definition", "class_definition", "decorated_definition"})


def _docstring(body: Node | None) -> str | None:
    if body is None:
        return None
    for child in named_children(body):
        if child.type == "comment":
            continue
        if child.type == "string":
            value = string_value(child)
            return value.strip() if value else None
        if child.type == "expression_statement" and child.named_child_count == 1:
            inner = child.named_children[0]
            if inner.type == "string":
                value = string_value(inner)
                return value.strip() if value else None
        return None
    return None


def _params(node: Node | None) -> list[str]:
    out: list[str] = []
    if node is None:
        return out
    for p in named_children(node):
        t = p.type
        if t == "identifier":
            out.append(text(p))
        elif t in ("typed_parameter",):
            inner = p.named_children[0] if p.named_child_count else None
            if inner is not None and inner.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                out.append(("*" if inner.type == "list_splat_pattern" else "**") + text(inner).lstrip("*"))
            elif inner is not None:
                out.append(text(inner))
        elif t in ("default_parameter", "typed_default_parameter"):
            name = field(p, "name")
            if name is not None:
                out.append(text(name))
        elif t == "list_splat_pattern":
            out.append("*" + text(p).lstrip("*"))
        elif t == "dictionary_splat_pattern":
            out.append("**" + text(p).lstrip("*"))
    return out


def _calls(body: Node | None, out: list[CallSite]) -> None:
    """Collect call sites under `body`, not descending into nested functions or classes."""
    if body is None:
        return
    stack = list(reversed(body.children))
    while stack:
        n = stack.pop()
        if n.type in _SCOPE_TYPES:
            continue
        if n.type == "call":
            fn = field(n, "function")
            if fn is not None:
                out.append(CallSite(callee=" ".join(text(fn).split()), line=start_line(n)))
        stack.extend(reversed(n.children))


class _PyParser:
    def __init__(self, path: str, source: bytes) -> None:
        self.path = path
        self.source = source
        self.lines = source_lines(source)
        self.symbols: list[Symbol] = []
        self.imports: list[ImportRec] = []
        self.exports: list[str] | None = None
        self.module_calls: list[CallSite] = []

    def run(self) -> ParsedFile:
        root = parse_tree("python", self.source)
        self._visit_block(root, None)
        self._collect_imports(root)
        pf = ParsedFile(path=self.path, language="python", tier=1, symbols=finalize(self.symbols),
                        imports=self.imports, exports=self.exports, module_calls=self.module_calls,
                        parse_error=bool(root.has_error))
        return pf

    def _visit_block(self, node: Node, scope: Symbol | None) -> None:
        for child in node.children:
            self._visit(child, scope)

    def _visit(self, node: Node, scope: Symbol | None) -> None:
        t = node.type
        if t == "decorated_definition":
            decorators = [text(d).lstrip("@").strip() for d in node.children if d.type == "decorator"]
            definition = field(node, "definition")
            if definition is not None:
                self._define(definition, scope, decorators, start_line(node))
        elif t in ("function_definition", "class_definition"):
            self._define(node, scope, [], start_line(node))
        elif t in _COMPOUND:
            self._visit_block(node, scope)
        elif t in ("expression_statement", "assignment") and scope is None:
            self._maybe_all(node)
            _calls(node, self.module_calls)
        elif scope is None:
            _calls(node, self.module_calls)

    def _define(self, node: Node, scope: Symbol | None, decorators: list[str], first: int) -> None:
        name_node = field(node, "name")
        if name_node is None:
            return
        name = text(name_node)
        last = end_line(node)
        qual = f"{scope.qualname}.{name}" if scope is not None else name
        body = field(node, "body")
        public = not name.startswith("_") or (name.startswith("__") and name.endswith("__"))
        if node.type == "class_definition":
            bases: list[str] = []
            sup = field(node, "superclasses")
            if sup is not None:
                bases = [text(a) for a in named_children(sup) if a.type not in ("keyword_argument", "comment")]
            sym = Symbol(kind="class", name=name, qualname=qual, start_line=first, end_line=last,
                         body=lines_text(self.lines, first, last), docstring=_docstring(body), bases=bases,
                         decorators=decorators, is_public=public, parent_obj=scope)
            self.symbols.append(sym)
            if body is not None:
                self._visit_block(body, sym)
            return
        is_async = any(c.type == "async" for c in node.children)
        kind: FunctionKind
        if scope is not None and scope.kind == "class":
            if name == "__init__":
                kind = "constructor"
            elif any(d == "property" or d.endswith((".setter", ".getter", ".deleter")) for d in decorators):
                kind = "property"
            else:
                kind = "method"
        elif scope is not None:
            kind = "nested"
        else:
            kind = "function"
        header_end = body.start_byte if body is not None else node.end_byte
        signature = " ".join(self.source[node.start_byte:header_end].decode("utf-8", "replace").split())
        signature = signature.rstrip(":").strip()
        rt = field(node, "return_type")
        sym = Symbol(kind="function", name=name, qualname=qual, start_line=first, end_line=last,
                     body=lines_text(self.lines, first, last), fn_kind=kind, docstring=_docstring(body),
                     signature=signature, parameters=_params(field(node, "parameters")),
                     return_type=text(rt) if rt is not None else None, decorators=decorators,
                     is_async=is_async, is_public=public, parent_obj=scope)
        _calls(body, sym.calls)
        self.symbols.append(sym)
        if body is not None:
            self._visit_nested(body, sym)

    def _visit_nested(self, node: Node, scope: Symbol) -> None:
        """Find functions and classes defined anywhere inside a function body."""
        for child in node.children:
            if child.type in ("decorated_definition", "function_definition", "class_definition"):
                self._visit(child, scope)
            elif child.type not in ("lambda",):
                self._visit_nested(child, scope)

    def _maybe_all(self, node: Node) -> None:
        for child in [node, *named_children(node)]:
            if child.type != "assignment":
                continue
            left = field(child, "left")
            right = field(child, "right")
            if left is None or right is None or text(left) != "__all__":
                continue
            if right.type in ("list", "tuple"):
                names = [string_value(e) for e in named_children(right) if e.type == "string"]
                self.exports = [n for n in names if n]

    def _collect_imports(self, root: Node) -> None:
        stack = [root]
        while stack:
            n = stack.pop()
            if n.type == "import_statement":
                for item in named_children(n):
                    if item.type == "dotted_name":
                        self.imports.append(ImportRec(module=text(item), line=start_line(n)))
                    elif item.type == "aliased_import":
                        mod = field(item, "name")
                        alias = field(item, "alias")
                        self.imports.append(ImportRec(module=text(mod), line=start_line(n),
                                                      alias=text(alias) if alias is not None else None))
                continue
            if n.type == "import_from_statement":
                self.imports.append(self._from_import(n))
                continue
            stack.extend(n.children)

    def _from_import(self, n: Node) -> ImportRec:
        mod_node = field(n, "module_name")
        level = 0
        module = ""
        if mod_node is not None:
            if mod_node.type == "relative_import":
                for c in mod_node.children:
                    if c.type == "import_prefix":
                        level = text(c).count(".")
                    elif c.type == "dotted_name":
                        module = text(c)
            else:
                module = text(mod_node)
        rec = ImportRec(module=module, line=start_line(n), level=level)
        for item in n.children:
            if mod_node is not None and item.start_byte == mod_node.start_byte:
                continue
            if item.type == "wildcard_import":
                rec.star = True
            elif item.type == "dotted_name":
                rec.names.append((text(item), text(item)))
            elif item.type == "aliased_import":
                name = text(field(item, "name"))
                alias = field(item, "alias")
                rec.names.append((name, text(alias) if alias is not None else name))
        return rec


def parse_python(path: str, source: bytes) -> ParsedFile:
    return _PyParser(path, source).run()
