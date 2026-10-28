"""Bundled demo cases: a small repo with a real bug, its issue text, and a replay script."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

from .config import CASES_DIR


@dataclass
class Case:
    slug: str
    title: str
    summary: str
    issue_title: str
    issue_body: str
    issue_ref: str
    repo: Path
    test_cmd: str
    timeout: float
    script: dict | None
    order: int = 99

    def public(self) -> dict:
        return {"slug": self.slug, "title": self.title, "summary": self.summary,
                "issue_title": self.issue_title, "issue_body": self.issue_body, "issue_ref": self.issue_ref,
                "test_cmd": self.test_cmd, "has_replay": self.script is not None}

    @property
    def issue_text(self) -> str:
        return f"{self.issue_title}\n\n{self.issue_body}"


def load_case(slug: str) -> Case:
    base = CASES_DIR / slug
    meta = json.loads((base / "case.json").read_text(encoding="utf-8"))
    script = None
    replay_py = base / "replay.py"
    if replay_py.exists():
        spec = importlib.util.spec_from_file_location(f"ft_replay_{slug}", replay_py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        script = mod.SCRIPT
    return Case(
        slug=slug, title=meta["title"], summary=meta["summary"],
        issue_title=meta["issue"]["title"], issue_body=meta["issue"]["body"], issue_ref=meta["issue"]["ref"],
        repo=base / "repo", test_cmd=meta.get("test_cmd", "pytest -q"),
        timeout=float(meta.get("timeout", 20)), script=script, order=int(meta.get("order", 99)),
    )


def list_cases() -> list[Case]:
    if not CASES_DIR.exists():
        return []
    cases = [load_case(p.name) for p in CASES_DIR.iterdir() if (p / "case.json").exists()]
    return sorted(cases, key=lambda c: (c.order, c.slug))
