"""Tree-sitter node types per tier-2 language (spec A, A6.4b).

Verified on 17 Oct 2026 against tree-sitter-language-pack 1.22.1 by parsing a sample file per language and
printing the node types (the table is repeated in docs/ingestion.md). Notes from that check:
- Kotlin: class and function names are not in a `name` field; they are the first `type_identifier` (class)
  or `simple_identifier` (function) child. `interface` parses as `class_declaration`. Calls are
  `call_expression` whose first child is the callee.
- Swift: `struct` and `enum` also parse as `class_declaration`; `init` is `init_declaration` (no name field).
- C: the function name sits inside the `declarator` chain (`function_declarator` > `identifier`).
- C++: methods defined inside a class are `function_definition` with a `field_identifier` name; out-of-class
  definitions use a `qualified_identifier` (`Shape::area`).
- Clojure: everything is a `list_lit`; a `sym_lit` has `name` (`sym_name`) and optional `namespace` (`sym_ns`).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LangMap:
    classes: frozenset[str]
    functions: frozenset[str]
    calls: frozenset[str]
    new_calls: frozenset[str] = frozenset()
    namespaces: frozenset[str] = frozenset()
    name_fields: tuple[str, ...] = ("name",)
    name_child_types: tuple[str, ...] = ()
    comment_markers: tuple[str, ...] = ("//", "/*", "*")
    private_words: tuple[str, ...] = ("private",)


def _fs(*items: str) -> frozenset[str]:
    return frozenset(items)


LANG_MAPS: dict[str, LangMap] = {
    "kotlin": LangMap(
        classes=_fs("class_declaration", "object_declaration"),
        functions=_fs("function_declaration"),
        calls=_fs("call_expression"),
        name_child_types=("type_identifier", "simple_identifier"),
    ),
    "ruby": LangMap(
        classes=_fs("class", "module"),
        functions=_fs("method", "singleton_method"),
        calls=_fs("call"),
        comment_markers=("#",),
    ),
    "php": LangMap(
        classes=_fs("class_declaration", "interface_declaration", "trait_declaration", "enum_declaration"),
        functions=_fs("function_definition", "method_declaration"),
        calls=_fs("function_call_expression", "member_call_expression", "scoped_call_expression"),
        new_calls=_fs("object_creation_expression"),
        namespaces=_fs("namespace_definition"),
        comment_markers=("//", "/*", "*", "#"),
    ),
    "c": LangMap(
        classes=_fs("struct_specifier", "union_specifier"),
        functions=_fs("function_definition"),
        calls=_fs("call_expression"),
        private_words=("static",),
    ),
    "cpp": LangMap(
        classes=_fs("class_specifier", "struct_specifier", "union_specifier"),
        functions=_fs("function_definition"),
        calls=_fs("call_expression"),
        new_calls=_fs("new_expression"),
        namespaces=_fs("namespace_definition"),
        private_words=("static",),
    ),
    "scala": LangMap(
        classes=_fs("class_definition", "object_definition", "trait_definition", "enum_definition"),
        functions=_fs("function_definition"),
        calls=_fs("call_expression"),
        new_calls=_fs("instance_expression"),
    ),
    "swift": LangMap(
        classes=_fs("class_declaration", "protocol_declaration"),
        functions=_fs("function_declaration", "init_declaration"),
        calls=_fs("call_expression"),
        name_child_types=("type_identifier", "simple_identifier"),
    ),
}

# Clojure is a Lisp: definitions are list forms named by their first symbol.
CLOJURE_FUNCTION_FORMS = frozenset({"defn", "defn-", "defmacro", "defmulti", "defmethod", "deftest"})
CLOJURE_CLASS_FORMS = frozenset({"defprotocol", "defrecord", "deftype"})
CLOJURE_SKIP_FORMS = frozenset({"comment"})
