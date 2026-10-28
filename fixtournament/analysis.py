"""Static blast-radius analysis for a candidate patch (no LLM involved).

For every function the patch touches, list the call sites in the repository,
split into production code and tests. A fix that edits a function with forty
callers deserves a different review than one with two.
"""

from __future__ import annotations

import ast
import difflib
from pathlib import Path

from .patching import is_protected

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"}


def _py_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def _defs(source: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    out.append((q, child.lineno, child.end_lineno or child.lineno))
                visit(child, q + ".")
            else:
                visit(child, prefix)

    try:
        visit(ast.parse(source))
    except SyntaxError:
        pass
    return out


def _call_index(root: Path) -> dict[str, list[tuple[str, int]]]:
    index: dict[str, list[tuple[str, int]]] = {}
    for p in _py_files(root):
        rel = str(p.relative_to(root))
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if name:
                    index.setdefault(name, []).append((rel, node.lineno))
    return index


def blast_radius(orig_root: Path, new_root: Path, paths: list[str]) -> list[dict]:
    index = _call_index(orig_root)
    results = []
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        before, after = orig_root / rel, new_root / rel
        if not before.exists() or not after.exists():
            continue
        a_src = before.read_text(encoding="utf-8")
        a, b = a_src.splitlines(), after.read_text(encoding="utf-8").splitlines()
        touched: set[int] = set()
        for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
            if tag != "equal":
                touched.update(range(i1 + 1, max(i2, i1 + 1) + 1))
        symbols: dict[str, tuple[int, int]] = {}
        for ln in touched:
            best = None
            for q, s, e in _defs(a_src):
                if s <= ln <= e and (best is None or (e - s) < (best[2] - best[1])):
                    best = (q, s, e)
            if best:
                symbols[best[0]] = (best[1], best[2])
        for q, (s, e) in symbols.items():
            name = q.split(".")[-1]
            sites = [(f, l) for f, l in index.get(name, []) if not (f == rel and s <= l <= e)]
            results.append({
                "symbol": q,
                "file": rel,
                "production": [{"file": f, "line": l} for f, l in sites if not is_protected(f)],
                "tests": [{"file": f, "line": l} for f, l in sites if is_protected(f)],
            })
    return results
