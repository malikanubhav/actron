"""A-AC-40: hunk parsing (additions, deletions, multiple hunks, no-newline markers, binary files) and mapping
changed lines to the innermost function, or to the class outside its methods."""

from __future__ import annotations

from actron.connectors.code.hunks import (
    Hunk,
    SymbolRange,
    map_hunks_to_symbols,
    new_ranges,
    parse_hunks,
    parse_patch,
)

PATCH = """\
diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -3,0 +4,2 @@ def f():
+    x = 1
+    y = 2
@@ -10,3 +11,0 @@ def g():
-    a
-    b
-    c
@@ -20 +19 @@ class K:
-    old
+    new
\\ No newline at end of file
diff --git a/img/logo.png b/img/logo.png
index 3333333..4444444 100644
Binary files a/img/logo.png and b/img/logo.png differ
diff --git a/old/name.ts b/new/name.ts
similarity index 90%
rename from old/name.ts
rename to new/name.ts
index 5555555..6666666 100644
--- a/old/name.ts
+++ b/new/name.ts
@@ -1 +1 @@
-export const a = 1;
+export const a = 2;
diff --git a/gone.py b/gone.py
deleted file mode 100644
index 7777777..0000000
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def gone():
-    pass
"""


def test_parse_hunks_forms() -> None:
    """A-AC-40"""
    hunks = parse_hunks(PATCH.split("diff --git a/img")[0])
    assert hunks == [Hunk(3, 0, 4, 2), Hunk(10, 3, 11, 0), Hunk(20, 1, 19, 1)]
    assert new_ranges(hunks) == [(4, 5), (11, 11), (19, 19)]
    assert new_ranges([Hunk(1, 2, 0, 0)]) == [(1, 1)]  # deletion at the top of the file


def test_parse_patch_files_binary_rename_delete() -> None:
    """A-AC-40"""
    files = parse_patch(PATCH)
    assert [f.path for f in files] == ["src/a.py", "img/logo.png", "new/name.ts", "gone.py"]
    assert files[1].binary and files[1].hunks == []
    assert files[2].old_path == "old/name.ts" and files[2].new_ranges() == [(1, 1)]
    assert files[3].old_ranges() == [(1, 2)]
    assert files[0].old_ranges() == [(10, 12), (20, 20)]


def test_map_to_innermost_symbol() -> None:
    """A-AC-40"""
    syms = [
        SymbolRange("K", "class", 1, 30),
        SymbolRange("K.method", "function", 3, 12),
        SymbolRange("K.method.inner", "function", 5, 7),
        SymbolRange("top", "function", 40, 45),
    ]
    touched = {t.key: (t.kind, t.lines_changed) for t in map_hunks_to_symbols(syms, [(4, 6), (20, 21), (35, 36), (45, 50)])}
    assert touched == {
        "K.method": ("function", 1),
        "K.method.inner": ("function", 2),
        "K": ("class", 2),
        "top": ("function", 1),
    }
