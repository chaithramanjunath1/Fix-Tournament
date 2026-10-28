"""The tournament: reproduce, diagnose, race, verify, review.

Everything the UI shows is an event on a single ordered log, so a browser that
connects late (or reconnects) replays the race from the start.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .agent import Contestant, Outcome, RaceContext, run_contestant
from .analysis import blast_radius
from .config import TIERS, cost_usd, model_for
from .llm import LLMError
from .patching import is_protected
from .sandbox import copy_repo

SOURCE_BUDGET = 22_000
FLAKE_RUNS = 3


class EventLog:
    def __init__(self):
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self.t0 = time.monotonic()

    def emit(self, type_: str, **data) -> None:
        with self._lock:
            ev = {"seq": len(self.events), "t": round(time.monotonic() - self.t0, 2), "type": type_, **data}
            self.events.append(ev)


def collect_sources(root: Path, budget: int = SOURCE_BUDGET) -> str:
    """Source files first, then tests (read-only reference), within a character budget."""
    files = [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]
    ordered = [p for p in files if not is_protected(str(p.relative_to(root)))] + \
              [p for p in files if is_protected(str(p.relative_to(root)))]
    chunks, used = [], 0
    for p in ordered:
        rel = str(p.relative_to(root))
        body = p.read_text(encoding="utf-8")
        tag = " (tests, read-only)" if is_protected(rel) else ""
        chunk = f"### {rel}{tag}\n```python\n{body}\n```"
        if used + len(chunk) > budget:
            chunks.append(f"### {rel}{tag}\n(omitted: size budget)")
            continue
        chunks.append(chunk)
        used += len(chunk)
    return "\n\n".join(chunks)


@dataclass
class Spec:
    repo: Path
    issue_text: str
    issue_title: str
    test_cmd: str | None
    timeout: float
    case_title: str = ""


def _json_from(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


class Tournament:
    def __init__(self, spec: Spec, llm, runner, roster: list[Contestant], mode: str,
                 log: EventLog, max_turns: int = 3):
        self.spec, self.llm, self.runner, self.roster = spec, llm, runner, roster
        self.mode = mode  # "qualify" or "sprint"
        self.log = log
        self.max_turns = max_turns
        self.cancel = threading.Event()
        self.workdir = Path(tempfile.mkdtemp(prefix="fixtournament-"))
        self.result: dict | None = None
        self.patch: str = ""
        self._ultra_tokens = [0, 0]  # planner + judge usage

    # -- helpers -----------------------------------------------------------
    def _ultra(self, role: str, system: str, user: str, **ctx):
        res = self.llm.complete(model=model_for("ultra"), role=role, temperature=0.1, max_tokens=1500,
                                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **ctx)
        self._ultra_tokens[0] += res.tokens_in
        self._ultra_tokens[1] += res.tokens_out
        return res

    def stop(self):
        self.cancel.set()

    # -- phases ------------------------------------------------------------
    def run(self) -> dict | None:
        emit = self.log.emit
        spec = self.spec
        try:
            emit("run.start", case=spec.case_title, issue_title=spec.issue_title, issue=spec.issue_text,
                 test_cmd=spec.test_cmd, mode=self.mode, source=self.llm.mode, runner=self.runner.name,
                 roster=[{"id": c.id, "name": c.name, "tier": c.tier, "strategy": c.strategy,
                          "model": model_for(c.tier)} for c in self.roster],
                 max_turns=self.max_turns)

            # 1. Reproduce ----------------------------------------------------
            emit("phase", phase="reproduce")
            pristine = copy_repo(spec.repo, self.workdir / "pristine")
            base = self.runner.run_tests(pristine, spec.test_cmd, spec.timeout)
            if base.timed_out or base.crashed or base.total == 0:
                emit("error", message="Could not run the test suite on the untouched repository.\n" + base.output[-800:])
                return None
            if base.green:
                emit("error", message="All tests already pass. Nothing to reproduce.")
                return None
            emit("reproduce.result", failing=base.failing, total=base.total, passed=base.passed,
                 output=base.output[-1800:])

            sources = collect_sources(pristine)

            # 2. Diagnose (Ultra) ---------------------------------------------
            emit("phase", phase="diagnose")
            try:
                d = self._ultra(
                    "diagnose",
                    "You are a principal engineer. Diagnose the bug in 3-6 plain sentences: which function is wrong, "
                    "why the failing tests fail, and what a correct fix must guarantee. Do not write code.",
                    f"## Issue\n{spec.issue_text}\n\n## Failing tests\n" + "\n".join(base.failing) +
                    f"\n\n## Output\n{base.output[-2500:]}\n\n## Repository\n{sources}")
            except LLMError as exc:
                emit("error", message=f"Diagnosis failed: {exc}")
                return None
            diagnosis = d.text.strip()
            emit("diagnose.result", text=diagnosis, model=model_for("ultra"), tokens_in=d.tokens_in,
                 tokens_out=d.tokens_out, latency=round(d.latency, 2))

            # 3. Race ---------------------------------------------------------
            emit("phase", phase="race")
            ctx = RaceContext(
                pristine=pristine, scratch=self.workdir / "race", test_cmd=spec.test_cmd, timeout=spec.timeout,
                llm=self.llm, runner=self.runner, emit=emit, issue_text=spec.issue_text,
                failure_output=base.output, failing=base.failing, baseline_total=base.total,
                diagnosis=diagnosis, sources=sources, max_turns=self.max_turns, cancel=self.cancel,
                stop_on_win=self.mode == "sprint")
            ctx.scratch.mkdir(parents=True, exist_ok=True)
            outcomes: dict[str, Outcome] = {}

            def work(c: Contestant) -> Outcome:
                o = run_contestant(ctx, c)
                if o.status == "passed" and self.mode == "sprint":
                    self.cancel.set()
                return o

            with ThreadPoolExecutor(max_workers=len(self.roster)) as pool:
                futures = {c.id: pool.submit(work, c) for c in self.roster}
                for cid, fut in futures.items():
                    outcomes[cid] = fut.result()

            if self.cancel.is_set() and not any(o.status == "passed" for o in outcomes.values()):
                emit("error", message="Run cancelled.")
                return None

            # 4. Rank + verify ------------------------------------------------
            emit("phase", phase="verify")
            ranking = self._rank(outcomes)
            winner = None
            for entry in ranking:
                if entry["eligible"] is False:
                    continue
                o = outcomes[entry["cid"]]
                runs = []
                for i in range(FLAKE_RUNS):
                    r = self.runner.run_tests(o.workspace, spec.test_cmd, spec.timeout)
                    runs.append({"green": r.green and r.total == base.total, "duration": r.duration})
                    emit("verify.run", cid=o.cid, index=i + 1, green=runs[-1]["green"], duration=r.duration)
                stable = all(x["green"] for x in runs)
                emit("verify.result", cid=o.cid, stable=stable, runs=runs)
                if stable:
                    winner = o
                    break
                entry["eligible"] = False
                entry["reason"] = "flaky: failed on re-run"
            for entry in ranking:
                if winner and entry["cid"] == winner.cid:
                    entry["rank"] = 1
            ranking = self._renumber(ranking, winner.cid if winner else None)

            # 5. Review (Ultra) -----------------------------------------------
            review, blast, pr = {}, [], {}
            if winner:
                blast = blast_radius(pristine, winner.workspace, winner.files)
                emit("phase", phase="judge")
                try:
                    j = self._ultra(
                        "judge",
                        "You are a staff engineer reviewing a bug-fix pull request. Reply with ONLY a JSON object with keys: "
                        "summary (one sentence), root_cause (one sentence), risk ('low'|'medium'|'high'), "
                        "risk_notes (array of short strings), follow_ups (array of short strings).",
                        f"## Issue\n{spec.issue_text}\n\n## Diagnosis\n{diagnosis}\n\n## Patch\n```diff\n{winner.diff}\n```\n\n"
                        f"## Blast radius\n{json.dumps(blast)[:1500]}\n\n## Verification\n"
                        f"{winner.passed}/{winner.total} tests green, stable across {FLAKE_RUNS} re-runs.",
                        winner=winner.cid)
                    review = _json_from(j.text) or {"summary": j.text[:240]}
                    review["model"] = model_for("ultra")
                except LLMError as exc:
                    review = {"summary": "Review unavailable.", "risk": "unknown", "risk_notes": [str(exc)]}
                pr = self._pr(winner, review, base, len(self.roster))
                self.patch = winner.diff

            costs = self._costs(outcomes)
            self.result = {
                "winner": winner.cid if winner else None,
                "ranking": ranking,
                "patch": self.patch,
                "blast": blast,
                "review": review,
                "pr": pr,
                "costs": costs,
                "baseline": {"total": base.total, "failing": base.failing},
            }
            emit("result", **self.result)
            emit("phase", phase="done")
            return self.result
        except Exception as exc:  # surface unexpected failures in the UI instead of hanging
            emit("error", message=f"Internal error: {type(exc).__name__}: {exc}")
            return None
        finally:
            threading.Thread(target=lambda: (time.sleep(120), shutil.rmtree(self.workdir, ignore_errors=True)),
                             daemon=True).start()

    # -- scoring -----------------------------------------------------------
    def _rank(self, outcomes: dict[str, Outcome]) -> list[dict]:
        names = {c.id: c for c in self.roster}
        passed = [o for o in outcomes.values() if o.status == "passed"]
        min_lines = min((o.added + o.removed for o in passed), default=1) or 1
        min_time = min((o.elapsed for o in passed), default=1) or 0.01
        min_cost = min((o.cost for o in passed), default=1) or 1e-9
        rows = []
        for o in outcomes.values():
            c = names[o.cid]
            row = {"cid": o.cid, "name": c.name, "tier": c.tier, "status": o.status, "reason": o.reason,
                   "turns": o.turns, "elapsed": o.elapsed, "cost": o.cost, "added": o.added, "removed": o.removed,
                   "passed": o.passed, "total": o.total, "eligible": o.status == "passed"}
            if o.status == "passed":
                lines = max(1, o.added + o.removed)
                parts = {
                    "correctness": 60.0,
                    "minimality": round(25.0 * min_lines / lines, 1),
                    "speed": round(10.0 * min_time / max(o.elapsed, 0.01), 1),
                    "economy": round(5.0 * min_cost / max(o.cost, 1e-9), 1),
                }
                row["parts"] = parts
                row["score"] = round(sum(parts.values()), 1)
            else:
                row["parts"] = {"correctness": 0, "minimality": 0, "speed": 0, "economy": 0}
                row["score"] = 0.0
            rows.append(row)
        rows.sort(key=lambda r: (-r["score"], r["elapsed"]))
        return rows

    @staticmethod
    def _renumber(rows: list[dict], winner: str | None) -> list[dict]:
        if winner:
            rows.sort(key=lambda r: (r["cid"] != winner, -r["score"], r["elapsed"]))
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        return rows

    def _costs(self, outcomes: dict[str, Outcome]) -> dict:
        by_tier = {t: 0.0 for t in TIERS}
        tin = sum(o.tokens_in for o in outcomes.values())
        tout = sum(o.tokens_out for o in outcomes.values())
        for c in self.roster:
            by_tier[c.tier] += outcomes[c.id].cost
        ultra_support = cost_usd("ultra", *self._ultra_tokens)
        by_tier["ultra"] += ultra_support
        routed = sum(by_tier.values())
        all_ultra = cost_usd("ultra", tin + self._ultra_tokens[0], tout + self._ultra_tokens[1])
        return {"routed": round(routed, 6), "all_ultra": round(all_ultra, 6), "by_tier": {k: round(v, 6) for k, v in by_tier.items()},
                "tokens_in": tin + self._ultra_tokens[0], "tokens_out": tout + self._ultra_tokens[1],
                "estimate": True}

    def _pr(self, w: Outcome, review: dict, base, n: int) -> dict:
        title = review.get("pr_title") or f"Fix: {self.spec.issue_title}"
        notes = review.get("risk_notes") or []
        body = [
            f"## Summary\n{review.get('summary', 'Fixes the failing tests.')}",
            f"## Root cause\n{review.get('root_cause', 'See diagnosis.')}",
            "## Verification\n"
            f"- {base.total - len(base.failing)}/{base.total} tests passed before; {w.passed}/{w.total} pass now\n"
            f"- Re-ran the full suite {FLAKE_RUNS}x on the winning patch: stable\n"
            "- No test files or test configuration were modified",
            f"## Risk: {review.get('risk', 'unrated')}\n" + ("\n".join(f"- {x}" for x in notes) if notes else "- none noted"),
            f"---\nSelected by Fix Tournament from {n} competing candidates "
            f"(winner: {self.roster_name(w.cid)}, {w.added + w.removed} changed lines).",
        ]
        return {"title": title, "body": "\n\n".join(body)}

    def roster_name(self, cid: str) -> str:
        return next(c.name for c in self.roster if c.id == cid)
