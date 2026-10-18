"""Generic extraction for tier-2 languages through the node-type maps in `lang_maps` (spec A, A6.4b)."""

from __future__ import annotations

from actron.connectors.code.lang_maps import (
    CLOJURE_CLASS_FORMS,
    CLOJURE_FUNCTION_FORMS,
    CLOJURE_SKIP_FORMS,
    LANG_MAPS,
    LangMap,
)
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


def _declarator_name(node: Node | None) -> str | None:
    """C/C++: follow the declarator chain to the identifier."""
    depth = 0
    while node is not None and depth < 8:
        if node.type in ("identifier", "field_identifier", "destructor_name", "operator_name"):
            return text(node)
        if node.type == "qualified_identifier":
            return text(node).replace("::", ".")
        node = field(node, "declarator")
        depth += 1
    return None


class _GenericParser:
    def __init__(self, path: str, source: bytes, language: str) -> None:
        self.path = path
        self.source = source
        self.language = language
        self.map: LangMap = LANG_MAPS[language]
        self.lines = source_lines(source)
        self.pf = ParsedFile(path=path, language=language, tier=2)

    def run(self) -> ParsedFile:
        root = parse_tree(self.language, self.source)
        self.pf.parse_error = bool(root.has_error)
        self._walk(root, None, "")
        finalize(self.pf.symbols)
        return self.pf

    def _name(self, node: Node) -> str | None:
        if self.language in ("c", "cpp") and node.type == "function_definition":
            return _declarator_name(field(node, "declarator"))
        if node.type == "init_declaration":
            return "init"
        for f in self.map.name_fields:
            n = field(node, f)
            if n is not None:
                return text(n)
        for c in node.children:
            if c.type in self.map.name_child_types:
                return text(c)
        return None

    def _callee(self, node: Node) -> CallSite | None:
        line = start_line(node)
        if node.type in self.map.new_calls:
            typ = field(node, "type") or next(iter(named_children(node)), None)
            return CallSite(text(typ).split("(", 1)[0].strip(), line, "new") if typ is not None else None
        fn = field(node, "function")
        if node.type == "call" and self.language == "ruby":
            method = field(node, "method")
            receiver = field(node, "receiver")
            if method is None:
                return None
            callee = f"{text(receiver)}.{text(method)}" if receiver is not None else text(method)
            return CallSite(callee, line, "new" if text(method) == "new" else "call")
        if node.type == "member_call_expression":
            obj, name = field(node, "object"), field(node, "name")
            return CallSite(f"{text(obj)}.{text(name)}".replace("$", ""), line) if name is not None else None
        if node.type == "scoped_call_expression":
            scope, name = field(node, "scope"), field(node, "name")
            return CallSite(f"{text(scope)}.{text(name)}", line) if name is not None else None
        if fn is None and node.named_child_count:
            fn = node.named_children[0]
        if fn is None:
            return None
        return CallSite("".join(text(fn).split()).replace("::", ".").replace("->", "."), line)

    def _walk(self, node: Node, scope: Symbol | None, ns: str) -> None:
        for child in node.children:
            t = child.type
            if t in self.map.namespaces:
                name_node = field(child, "name")
                inner_ns = f"{ns}{text(name_node)}." if name_node is not None else ns
                if self.language == "php" and field(child, "body") is None:
                    self.pf.namespace = text(name_node) if name_node is not None else None
                self._walk(child, scope, inner_ns)
            elif t in self.map.classes and (field(child, "body") is not None or t not in (
                    "struct_specifier", "union_specifier")):
                self._define(child, scope, ns, "class")
            elif t in self.map.functions:
                self._define(child, scope, ns, "function")
            elif t in self.map.calls or t in self.map.new_calls:
                site = self._callee(child)
                if site is not None:
                    (scope.calls if scope is not None and scope.kind == "function" else self.pf.module_calls).append(site)
                self._walk(child, scope, ns)
            else:
                self._walk(child, scope, ns)

    def _define(self, node: Node, scope: Symbol | None, ns: str, kind: str) -> None:
        name = self._name(node)
        if not name:
            self._walk(node, scope, ns)
            return
        first, last = start_line(node), end_line(node)
        qual = f"{scope.qualname}.{name}" if scope is not None else f"{ns}{name}"
        header = self.lines[first - 1] if first - 1 < len(self.lines) else ""
        public = not any(w in header.split() for w in self.map.private_words)
        if kind == "class":
            sym = Symbol(kind="class", name=name, qualname=qual, start_line=first, end_line=last,
                         body=lines_text(self.lines, first, last),
                         docstring=leading_comment(self.lines, first, self.map.comment_markers), is_public=public,
                         parent_obj=scope)
        else:
            if scope is not None and scope.kind == "class":
                fn_kind = "constructor" if name in ("init", "__construct", "initialize", "constructor") else "method"
            elif scope is not None:
                fn_kind = "nested"
            else:
                fn_kind = "function"
            sym = Symbol(kind="function", name=name.rsplit(".", 1)[-1], qualname=qual, start_line=first,
                         end_line=last, body=lines_text(self.lines, first, last), fn_kind=fn_kind,  # type: ignore[arg-type]
                         docstring=leading_comment(self.lines, first, self.map.comment_markers),
                         signature=" ".join(header.split()), is_public=public, parent_obj=scope)
        self.pf.symbols.append(sym)
        self._walk(node, sym, ns)


# Clojure


def _sym_parts(node: Node) -> tuple[str | None, str]:
    ns = field(node, "namespace")
    name = field(node, "name")
    return (text(ns) if ns is not None else None), (text(name) if name is not None else text(node))


def _forms(node: Node) -> list[Node]:
    return [c for c in node.children if c.is_named and c.type not in ("comment", "dis_expr")]


def _head(form: Node) -> Node | None:
    items = _forms(form)
    if items and items[0].type == "sym_lit":
        return items[0]
    return None


class _ClojureParser:
    def __init__(self, path: str, source: bytes) -> None:
        self.source = source
        self.lines = source_lines(source)
        self.pf = ParsedFile(path=path, language="clojure", tier=2)

    def run(self) -> ParsedFile:
        root = parse_tree("clojure", self.source)
        self.pf.parse_error = bool(root.has_error)
        self._top(root)
        finalize(self.pf.symbols)
        return self.pf

    def _top(self, container: Node) -> None:
        for form in _forms(container):
            if form.type != "list_lit":
                continue
            head = _head(form)
            hname = _sym_parts(head)[1] if head is not None else None
            if hname == "ns":
                self._ns(form)
            elif hname in CLOJURE_FUNCTION_FORMS or hname in CLOJURE_CLASS_FORMS:
                self._def(form, hname)
            elif hname in CLOJURE_SKIP_FORMS:
                continue
            else:
                self._calls(form, self.pf.module_calls)
                self._top(form)

    def _ns(self, form: Node) -> None:
        items = _forms(form)
        if len(items) > 1 and items[1].type == "sym_lit":
            self.pf.namespace = text(items[1]).split()[-1]
        for clause in items[2:]:
            if clause.type != "list_lit":
                continue
            parts = _forms(clause)
            if not parts or parts[0].type != "kwd_lit" or text(parts[0]) not in (":require", ":use"):
                continue
            for spec in parts[1:]:
                self._require(spec)

    def _require(self, spec: Node) -> None:
        line = start_line(spec)
        if spec.type in ("sym_lit", "str_lit"):
            mod = text(spec) if spec.type == "sym_lit" else (string_value(spec) or "")
            self.pf.imports.append(ImportRec(module=mod, line=line))
            return
        if spec.type not in ("vec_lit", "list_lit"):
            return
        parts = _forms(spec)
        if not parts:
            return
        head = parts[0]
        module_name = string_value(head) if head.type == "str_lit" else text(head)
        rec = ImportRec(module=module_name or "", line=line)
        i = 1
        while i < len(parts):
            kw = text(parts[i])
            nxt = parts[i + 1] if i + 1 < len(parts) else None
            if kw in (":as", ":as-alias") and nxt is not None:
                rec.alias = text(nxt)
            elif kw == ":refer" and nxt is not None:
                if nxt.type == "vec_lit":
                    rec.names.extend((text(s), text(s)) for s in _forms(nxt) if s.type == "sym_lit")
                elif text(nxt) == ":all":
                    rec.star = True
            i += 2 if nxt is not None and kw.startswith(":") else 1
        self.pf.imports.append(rec)

    def _def(self, form: Node, head: str) -> None:
        items = _forms(form)
        if len(items) < 2 or items[1].type != "sym_lit":
            return
        name = _sym_parts(items[1])[1]
        meta = text(items[1])
        first, last = start_line(form), end_line(form)
        doc = None
        params: list[str] = []
        for it in items[2:]:
            if it.type == "str_lit" and doc is None and head not in ("defrecord", "deftype"):
                doc = string_value(it)
            elif it.type == "vec_lit":
                params = [text(p) for p in _forms(it)]
                break
            elif it.type == "list_lit":
                break
        public = head != "defn-" and "^:private" not in meta and ":private true" not in meta
        if head in CLOJURE_CLASS_FORMS:
            sym = Symbol(kind="class", name=name, qualname=name, start_line=first, end_line=last,
                         body=lines_text(self.lines, first, last), docstring=doc, is_public=public)
        else:
            sym = Symbol(kind="function", name=name, qualname=name, start_line=first, end_line=last,
                         body=lines_text(self.lines, first, last), fn_kind="function", docstring=doc,
                         signature=f"({head} {name} [{' '.join(params)}])" if params else f"({head} {name})",
                         parameters=params, decorators=[head], is_public=public, is_test=head == "deftest")
            for body_form in items[2:]:
                self._calls(body_form, sym.calls)
        self.pf.symbols.append(sym)

    def _calls(self, node: Node, out: list[CallSite]) -> None:
        stack = [node]
        while stack:
            n = stack.pop()
            if n.type == "list_lit":
                head = _head(n)
                if head is not None:
                    ns, name = _sym_parts(head)
                    out.append(CallSite(f"{ns}/{name}" if ns else name, start_line(n)))
            stack.extend(reversed([c for c in n.children if c.is_named]))
        out.sort(key=lambda c: c.line)


def parse_generic(path: str, source: bytes, language: str) -> ParsedFile:
    if language == "clojure":
        return _ClojureParser(path, source).run()
    return _GenericParser(path, source, language).run()
