"""TypeScript, TSX and JavaScript parsing (spec A, A6.4).

Functions: declarations, methods, arrow functions and function expressions assigned to names, default
exports, and test callbacks passed to `it`/`test` (named by their first string argument, qualified by the
enclosing `describe`/`suite` strings joined with ` > `). Classes: classes, abstract classes, interfaces.
"""

from __future__ import annotations

from actron.connectors.code.model import CallSite, ImportRec, ParsedFile, Symbol, finalize
from actron.connectors.code.ts_util import (
    Node,
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

_FUNC_VALUES = frozenset({"arrow_function", "function_expression", "function", "generator_function"})
_FUNC_DECLS = frozenset({"function_declaration", "generator_function_declaration", "function_signature"})
_CLASS_DECLS = frozenset({"class_declaration", "abstract_class_declaration", "class"})
SUITE_CALLS = frozenset({"describe", "suite", "context"})
TEST_CALLS = frozenset({"it", "test", "specify"})
_GRAMMARS = {"typescript": "typescript", "tsx": "tsx", "javascript": "javascript"}


def _clean_callee(raw: str) -> str:
    s = "".join(raw.split())
    return s.replace("?.", ".").replace("!.", ".")


def _call_root_name(fn: Node | None) -> str | None:
    """`describe`, `describe.only`, `it.skip` → the root identifier."""
    if fn is None:
        return None
    if fn.type == "identifier":
        return text(fn)
    if fn.type == "member_expression":
        obj = field(fn, "object")
        if obj is not None and obj.type == "identifier":
            return text(obj)
    return None


def _params(node: Node | None) -> list[str]:
    if node is None:
        return []
    if node.type == "identifier":
        return [text(node)]
    out: list[str] = []
    for p in named_children(node):
        if p.type in ("required_parameter", "optional_parameter"):
            pat = field(p, "pattern")
            out.append(text(pat) if pat is not None else text(p))
        elif p.type == "identifier":
            out.append(text(p))
        elif p.type == "assignment_pattern":
            left = field(p, "left")
            out.append(text(left) if left is not None else text(p))
        elif p.type == "rest_pattern" or p.type not in ("comment",):
            out.append(text(p))
    return out


class _TsParser:
    def __init__(self, path: str, source: bytes, language: str) -> None:
        self.path = path
        self.source = source
        self.language = language
        self.lines = source_lines(source)
        self.symbols: list[Symbol] = []
        self.imports: list[ImportRec] = []
        self.module_calls: list[CallSite] = []
        self.exported_names: set[str] = set()
        self.default_export: str | None = None

    def run(self) -> ParsedFile:
        root = parse_tree(_GRAMMARS[self.language], self.source)
        self._scan_children(root, None, [], False)
        for sym in self.symbols:
            if sym.parent_obj is None and sym.name in self.exported_names:
                sym.is_public = True
        finalize(self.symbols)
        return ParsedFile(path=self.path, language=self.language, tier=1, symbols=self.symbols,
                          imports=self.imports, module_calls=self.module_calls,
                          default_export=self.default_export, parse_error=bool(root.has_error))

    # Helpers
    def _calls_of(self, scope: Symbol | None) -> list[CallSite]:
        return scope.calls if scope is not None else self.module_calls

    def _signature(self, node: Node, body: Node | None) -> str:
        end = body.start_byte if body is not None else node.end_byte
        sig = " ".join(self.source[node.start_byte:end].decode("utf-8", "replace").split())
        return sig.rstrip("{").rstrip("=>").strip()

    def _qual(self, scope: Symbol | None, name: str) -> str:
        return f"{scope.qualname}.{name}" if scope is not None else name

    def _make_fn(self, node: Node, outer: Node, name: str, scope: Symbol | None, *, exported: bool,
                 kind: str | None = None, decorators: list[str] | None = None, public: bool | None = None,
                 qualname: str | None = None, is_test: bool = False) -> Symbol:
        first, last = start_line(outer), end_line(outer)
        body = field(node, "body")
        if kind is None:
            if scope is None:
                kind = "function"
            elif scope.kind == "class":
                kind = "method"
            else:
                kind = "nested"
        rt = field(node, "return_type")
        sym = Symbol(
            kind="function", name=name, qualname=qualname or self._qual(scope, name), start_line=first,
            end_line=last, body=lines_text(self.lines, first, last), fn_kind=kind,  # type: ignore[arg-type]
            docstring=leading_comment(self.lines, first), signature=self._signature(node, body),
            parameters=_params(field(node, "parameters") or field(node, "parameter")),
            return_type=text(rt).lstrip(":").strip() if rt is not None else None,
            decorators=decorators or [], is_async=any(c.type == "async" for c in node.children),
            is_public=exported if public is None else public, is_test=is_test, parent_obj=scope,
        )
        self.symbols.append(sym)
        return sym

    # Walking
    def _scan_children(self, node: Node, scope: Symbol | None, suites: list[str], exported: bool) -> None:
        pending_decorators: list[str] = []
        for child in node.children:
            if child.type == "decorator":
                pending_decorators.append(text(child).lstrip("@").strip())
                continue
            self._scan(child, scope, suites, exported, pending_decorators)
            pending_decorators = []

    def _scan(self, node: Node, scope: Symbol | None, suites: list[str], exported: bool,
              decorators: list[str] | None = None, outer: Node | None = None) -> None:
        t = node.type
        outer = outer or node
        if t == "export_statement":
            self._export(node, scope, suites)
        elif t in _FUNC_DECLS:
            name_node = field(node, "name")
            if name_node is None or field(node, "body") is None:
                return
            sym = self._make_fn(node, outer, text(name_node), scope, exported=exported)
            self._scan_body(field(node, "body"), sym, suites)
        elif t in _CLASS_DECLS:
            self._class(node, outer, scope, suites, exported, decorators or [])
        elif t == "interface_declaration":
            self._interface(node, outer, scope, exported)
        elif t in ("lexical_declaration", "variable_declaration"):
            self._variables(node, outer, scope, suites, exported)
        elif t == "import_statement":
            self._import(node)
        elif t == "call_expression":
            self._call(node, scope, suites)
        elif t == "new_expression":
            ctor = field(node, "constructor")
            if ctor is not None:
                self._calls_of(scope).append(CallSite(_clean_callee(text(ctor)), start_line(node), "new"))
            self._scan_children(node, scope, suites, False)
        elif t == "assignment_expression" and scope is None:
            self._assignment(node, scope, suites)
        elif t in _FUNC_VALUES:
            # an anonymous function that is not assigned to a name: its calls belong to the enclosing scope
            self._scan_children(node, scope, suites, False)
        else:
            self._scan_children(node, scope, suites, False)

    def _scan_body(self, body: Node | None, scope: Symbol | None, suites: list[str]) -> None:
        if body is None:
            return
        if body.type in ("statement_block", "class_body"):
            self._scan_children(body, scope, suites, False)
        else:  # arrow function expression body
            self._scan(body, scope, suites, False)

    def _export(self, node: Node, scope: Symbol | None, suites: list[str]) -> None:
        decorators = [text(c).lstrip("@").strip() for c in node.children if c.type == "decorator"]
        decl = field(node, "declaration")
        value = field(node, "value")
        source = field(node, "source")
        if source is not None:
            rec = ImportRec(module=string_value(source) or "", line=start_line(node))
            clause = next((c for c in node.children if c.type == "export_clause"), None)
            if clause is None:
                rec.star = True
                ns = next((c for c in node.children if c.type in ("namespace_export",)), None)
                if ns is not None:
                    rec.alias = text(ns).replace("*", "").replace("as", "").strip() or None
            else:
                for spec in named_children(clause):
                    if spec.type == "export_specifier":
                        nm = text(field(spec, "name"))
                        al = field(spec, "alias")
                        rec.names.append((nm, text(al) if al is not None else nm))
                        self.exported_names.add(text(al) if al is not None else nm)
            self.imports.append(rec)
            return
        is_default = any(c.type == "default" for c in node.children)
        if decl is not None:
            self._scan(decl, scope, suites, True, decorators, outer=node)
            name_node = field(decl, "name")
            if is_default and name_node is not None:
                self.default_export = text(name_node)
            return
        if value is not None:
            if value.type in _FUNC_VALUES or value.type in _CLASS_DECLS:
                name_node = field(value, "name")
                name = text(name_node) if name_node is not None else "default"
                self.default_export = name
                if value.type in _CLASS_DECLS:
                    self._class(value, node, scope, suites, True, decorators, name=name)
                else:
                    sym = self._make_fn(value, node, name, scope, exported=True)
                    self._scan_body(field(value, "body"), sym, suites)
            else:
                if value.type == "identifier":
                    self.exported_names.add(text(value))
                    self.default_export = text(value)
                self._scan(value, scope, suites, False)
            return
        clause = next((c for c in node.children if c.type == "export_clause"), None)
        if clause is not None:
            for spec in named_children(clause):
                if spec.type == "export_specifier":
                    self.exported_names.add(text(field(spec, "name")))

    def _import(self, node: Node) -> None:
        source = field(node, "source")
        rec = ImportRec(module=string_value(source) or "", line=start_line(node))
        clause = next((c for c in node.children if c.type == "import_clause"), None)
        if clause is not None:
            for part in named_children(clause):
                if part.type == "identifier":
                    rec.names.append(("default", text(part)))
                elif part.type == "namespace_import":
                    ident = next((c for c in part.children if c.type == "identifier"), None)
                    rec.alias = text(ident) if ident is not None else None
                elif part.type == "named_imports":
                    for spec in named_children(part):
                        if spec.type == "import_specifier":
                            nm = text(field(spec, "name"))
                            al = field(spec, "alias")
                            rec.names.append((nm, text(al) if al is not None else nm))
        self.imports.append(rec)

    def _class(self, node: Node, outer: Node, scope: Symbol | None, suites: list[str], exported: bool,
               decorators: list[str], name: str | None = None) -> None:
        name_node = field(node, "name")
        if name is None:
            name = text(name_node) if name_node is not None else "default"
        decorators = decorators + [text(c).lstrip("@").strip() for c in node.children if c.type == "decorator"]
        bases: list[str] = []
        for c in node.children:
            if c.type == "class_heritage":
                for clause in named_children(c):
                    for v in named_children(clause):
                        if v.type not in ("comment", "type_arguments"):
                            bases.append(text(v))
        first, last = start_line(outer), end_line(outer)
        sym = Symbol(kind="class", name=name, qualname=self._qual(scope, name), start_line=first, end_line=last,
                     body=lines_text(self.lines, first, last), docstring=leading_comment(self.lines, first),
                     bases=bases, decorators=decorators, is_public=exported, parent_obj=scope)
        self.symbols.append(sym)
        body = field(node, "body")
        if body is None:
            return
        pending: list[str] = []
        for member in body.children:
            if member.type == "decorator":
                pending.append(text(member).lstrip("@").strip())
                continue
            self._member(member, sym, suites, exported, pending)
            pending = []

    def _member(self, member: Node, cls: Symbol, suites: list[str], exported: bool, decorators: list[str]) -> None:
        private = any(c.type == "accessibility_modifier" and text(c) in ("private", "protected")
                      for c in member.children)
        if member.type == "method_definition":
            name_node = field(member, "name")
            if name_node is None:
                return
            name = text(name_node)
            if any(c.type in ("get", "set") for c in member.children):
                kind = "property"
            elif name == "constructor":
                kind = "constructor"
            else:
                kind = "method"
            public = exported and not private and not name.startswith("#")
            sym = self._make_fn(member, member, name, cls, exported=exported, kind=kind,
                                decorators=decorators, public=public)
            self._scan_body(field(member, "body"), sym, suites)
        elif member.type in ("public_field_definition", "field_definition"):
            value = field(member, "value")
            name_node = field(member, "name") or field(member, "property")
            if value is not None and value.type in _FUNC_VALUES and name_node is not None:
                name = text(name_node)
                sym = self._make_fn(value, member, name, cls, exported=exported, kind="method",
                                    decorators=decorators, public=exported and not private)
                self._scan_body(field(value, "body"), sym, suites)
            elif value is not None:
                self._scan(value, cls, suites, False)
        elif member.type == "class_static_block":
            self._scan_children(member, cls, suites, False)

    def _interface(self, node: Node, outer: Node, scope: Symbol | None, exported: bool) -> None:
        name_node = field(node, "name")
        if name_node is None:
            return
        bases: list[str] = []
        for c in node.children:
            if c.type in ("extends_type_clause", "extends_clause"):
                bases.extend(text(v) for v in named_children(c))
        first, last = start_line(outer), end_line(outer)
        self.symbols.append(Symbol(
            kind="class", name=text(name_node), qualname=self._qual(scope, text(name_node)), start_line=first,
            end_line=last, body=lines_text(self.lines, first, last), docstring=leading_comment(self.lines, first),
            bases=bases, is_public=exported, parent_obj=scope,
        ))

    def _variables(self, node: Node, outer: Node, scope: Symbol | None, suites: list[str], exported: bool) -> None:
        declarators = [c for c in node.children if c.type == "variable_declarator"]
        for decl in declarators:
            name_node = field(decl, "name")
            value = field(decl, "value")
            if value is None:
                continue
            if name_node is not None and name_node.type == "identifier" and value.type in _FUNC_VALUES:
                range_node = outer if len(declarators) == 1 else decl
                sym = self._make_fn(value, range_node, text(name_node), scope, exported=exported)
                self._scan_body(field(value, "body"), sym, suites)
                continue
            if value.type in _CLASS_DECLS and name_node is not None:
                range_node = outer if len(declarators) == 1 else decl
                self._class(value, range_node, scope, suites, exported, [], name=text(name_node))
                continue
            if value.type == "call_expression" and _call_root_name(field(value, "function")) == "require":
                args = field(value, "arguments")
                arg = args.named_children[0] if args is not None and args.named_child_count else None
                if arg is not None and arg.type == "string":
                    rec = ImportRec(module=string_value(arg) or "", line=start_line(decl), dynamic=True)
                    if name_node is not None and name_node.type == "identifier":
                        rec.alias = text(name_node)
                    elif name_node is not None and name_node.type == "object_pattern":
                        for p in named_children(name_node):
                            if p.type == "shorthand_property_identifier_pattern":
                                rec.names.append((text(p), text(p)))
                    self.imports.append(rec)
                    continue
            self._scan(value, scope, suites, False)

    def _assignment(self, node: Node, scope: Symbol | None, suites: list[str]) -> None:
        left = field(node, "left")
        right = field(node, "right")
        if left is not None and right is not None and right.type in _FUNC_VALUES and left.type == "member_expression":
            parts = _clean_callee(text(left)).split(".")
            name = parts[-1]
            if parts[:1] in (["exports"], ["module"]):
                sym = self._make_fn(right, node, name, scope, exported=True)
            elif len(parts) == 3 and parts[1] == "prototype":
                sym = self._make_fn(right, node, name, scope, exported=False, kind="method",
                                    qualname=f"{parts[0]}.{name}")
            else:
                self._scan_children(node, scope, suites, False)
                return
            self._scan_body(field(right, "body"), sym, suites)
            return
        self._scan_children(node, scope, suites, False)

    def _call(self, node: Node, scope: Symbol | None, suites: list[str]) -> None:
        fn = field(node, "function")
        args = field(node, "arguments")
        line = start_line(node)
        if fn is not None and fn.type == "import":
            arg = args.named_children[0] if args is not None and args.named_child_count else None
            if arg is not None and arg.type == "string":
                self.imports.append(ImportRec(module=string_value(arg) or "", line=line, dynamic=True))
            return
        root = _call_root_name(fn)
        if fn is not None:
            self._calls_of(scope).append(CallSite(_clean_callee(text(fn)), line))
        arg_nodes = named_children(args) if args is not None else []
        if root == "require" and arg_nodes and arg_nodes[0].type == "string":
            self.imports.append(ImportRec(module=string_value(arg_nodes[0]) or "", line=line, dynamic=True))
            return
        if root in SUITE_CALLS | TEST_CALLS and len(arg_nodes) >= 2 and arg_nodes[0].type in (
            "string", "template_string"
        ):
            title = (string_value(arg_nodes[0]) or "").replace("~", "-").strip()
            callback = next((a for a in arg_nodes[1:] if a.type in _FUNC_VALUES), None)
            if callback is not None:
                if root in SUITE_CALLS:
                    self._scan_body(field(callback, "body"), scope, [*suites, title])
                    return
                name = " > ".join([*suites, title])
                kind = "nested" if scope is not None and scope.kind == "function" else "function"
                sym = self._make_fn(callback, node, title, scope, exported=False, kind=kind,
                                    qualname=name if scope is None else f"{scope.qualname}.{name}", is_test=True)
                self._scan_body(field(callback, "body"), sym, suites)
                return
        if fn is not None and fn.type == "member_expression":
            obj = field(fn, "object")
            if obj is not None:
                self._scan(obj, scope, suites, False)
        if args is not None:
            self._scan_children(args, scope, suites, False)


def parse_typescript(path: str, source: bytes, language: str = "typescript") -> ParsedFile:
    return _TsParser(path, source, language).run()
