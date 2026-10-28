"""Search/replace edit blocks: parse model output, apply it safely, produce diffs.

Models are asked for edits in this format:

    FILE: pkg/module.py
    <<<<<<< SEARCH
    exact existing lines
    =======
    replacement lines
    >>>>>>> REPLACE

Edits are more robust than asking for whole files: they are small, reviewable,
and an inexact SEARCH is detected instead of silently clobbering code.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

BLOCK = re.compile(
    r"^FILE:[ \t]*(?P<path>[^\n]+?)[ \t]*\n<<<<<<< SEARCH[ \t]*\n(?P<search>.*?)^=======[ \t]*\n(?P<replace>.*?)^>>>>>>> REPLACE[ \t]*$",
    re.S | re.M,
)

PROTECTED_NAMES = {"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "noxfile.py"}


@dataclass
class Edit:
    path: str
    search: str
    replace: str


@dataclass
class ApplyResult:
    changed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_protected(path: str) -> bool:
    """Files an agent must never touch: tests and test configuration."""
    p = Path(path)
    name = p.name
    if name in PROTECTED_NAMES:
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in ("tests", "test") for part in p.parts[:-1])


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _trim_nl(s: str) -> str:
    return s[:-1] if s.endswith("\n") else s


def parse_edits(text: str) -> list[Edit]:
    edits = []
    for m in BLOCK.finditer(text):
        path = m.group("path").strip().strip("`'\"")
        edits.append(Edit(path=path, search=_trim_nl(m.group("search")), replace=_trim_nl(m.group("replace"))))
    return edits


def _safe_path(root: Path, rel: str) -> Path | None:
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _fuzzy_hits(text: str, search: str) -> list[int]:
    lines = [l.rstrip() for l in text.split("\n")]
    want = [l.rstrip() for l in search.split("\n")]
    n = len(want)
    return [i for i in range(len(lines) - n + 1) if lines[i : i + n] == want]


def apply_edits(root: Path, edits: list[Edit]) -> ApplyResult:
    result = ApplyResult()
    for e in edits:
        target = _safe_path(root, e.path)
        if target is None:
            result.errors.append(f"{e.path}: path is outside the repository")
            continue
        if not target.exists():
            if e.search.strip() == "":
                target.parent.mkdir(parents=True, exist_ok=True)
                _write(target, e.replace + "\n")
                if e.path not in result.changed:
                    result.changed.append(e.path)
                continue
            result.errors.append(f"{e.path}: file does not exist")
            continue
        text = target.read_text(encoding="utf-8")
        if e.search.strip() == "":
            result.errors.append(f"{e.path}: empty SEARCH is only allowed when creating a new file")
            continue
        count = text.count(e.search)
        if count == 1:
            new = text.replace(e.search, e.replace, 1)
        elif count > 1:
            result.errors.append(f"{e.path}: SEARCH block matches {count} places; include more surrounding lines")
            continue
        else:
            hits = _fuzzy_hits(text, e.search)
            if len(hits) != 1:
                first = e.search.split("\n")[0].strip()[:80]
                result.errors.append(f"{e.path}: SEARCH block not found (starts with: {first!r}); copy lines exactly")
                continue
            lines = text.split("\n")
            n = len(e.search.split("\n"))
            lines[hits[0] : hits[0] + n] = e.replace.split("\n")
            new = "\n".join(lines)
        _write(target, new)
        if e.path not in result.changed:
            result.changed.append(e.path)
    return result


def make_diff(orig_root: Path, new_root: Path, paths: list[str]) -> str:
    chunks = []
    for rel in sorted(paths):
        a = (orig_root / rel)
        b = (new_root / rel)
        a_lines = a.read_text(encoding="utf-8").splitlines(keepends=True) if a.exists() else []
        b_lines = b.read_text(encoding="utf-8").splitlines(keepends=True) if b.exists() else []
        diff = difflib.unified_diff(
            a_lines, b_lines,
            fromfile=f"a/{rel}" if a.exists() else "/dev/null",
            tofile=f"b/{rel}",
        )
        chunks.append("".join(l if l.endswith("\n") else l + "\n" for l in diff))
    return "".join(chunks)


def diff_stats(diff: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed
