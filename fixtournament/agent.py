"""One contestant: read, patch, test, learn from the failure, repeat.

Every turn starts from a pristine copy of the repo and asks for a complete set
of edits against the original files. That keeps each attempt independent and
makes the final patch exactly what was tested.
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import cost_usd, model_for
from .llm import LLMError
from .patching import apply_edits, diff_stats, is_protected, make_diff, parse_edits
from .sandbox import copy_repo

STRATEGIES = {
    "minimal": ("Minimal", "Change as few lines as possible. Prefer a one- or two-line fix. Do not refactor."),
    "rootcause": ("Root cause", "Trace the failure to its root cause and fix it there, once, instead of patching symptoms."),
    "defensive": ("Defensive", "Fix the bug, and also guard the obvious adjacent edge cases that the same flaw would affect."),
    "refactor": ("Refactor", "If the structure of the code is what causes the bug, restructure the affected function cleanly. Keep public behaviour and signatures."),
}

SYSTEM = """You are an automated code-patching engine.
Output ONLY the edit block below. Do NOT write any introduction, thinking, explanation, or markdown code fences (```).
Start your response immediately on line 1 with "FILE:":

FILE: path/relative/to/repo.py
<<<<<<< SEARCH
exact existing lines to replace
=======
replacement lines
>>>>>>> REPLACE
"""


@dataclass
class Contestant:
    id: str
    tier: str
    strategy: str
    temperature: float = 0.3

    @property
    def name(self) -> str:
        return f"{self.tier.capitalize()} · {STRATEGIES[self.strategy][0]}"


def build_roster(size: int) -> list[Contestant]:
    order = []
    for strat in ("minimal", "rootcause", "defensive", "refactor"):
        for tier in ("nano", "super"):
            order.append(Contestant(id=f"{tier}-{strat}", tier=tier, strategy=strat,
                                    temperature=0.2 if strat == "minimal" else 0.4))
    return order[: max(2, min(size, len(order)))]


@dataclass
class RaceContext:
    pristine: Path
    scratch: Path
    test_cmd: str | None
    timeout: float
    llm: object
    runner: object
    emit: callable
    issue_text: str
    failure_output: str
    failing: list[str]
    baseline_total: int
    diagnosis: str
    sources: str
    max_turns: int
    cancel: threading.Event = field(default_factory=threading.Event)
    stop_on_win: bool = False


@dataclass
class Outcome:
    cid: str
    status: str = "failed"        # passed | failed | disqualified | timeout | error | cancelled
    reason: str = ""
    turns: int = 0
    elapsed: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    diff: str = ""
    added: int = 0
    removed: int = 0
    files: list[str] = field(default_factory=list)
    workspace: Path | None = None
    passed: int = 0
    total: int = 0


def _user_prompt(ctx: RaceContext, c: Contestant, turn: int, prev_diff: str, prev_feedback: str) -> str:
    parts = [
        f"## Issue\n{ctx.issue_text}",
        "## Failing tests (baseline)\n" + "\n".join(f"- {t}" for t in ctx.failing),
        f"## Failure output\n```\n{ctx.failure_output[-2500:]}\n```",
        f"## Diagnosis from a senior colleague\n{ctx.diagnosis}",
        f"## Your approach\n{STRATEGIES[c.strategy][1]}",
        f"## Repository\n{ctx.sources}",
    ]
    if turn > 1:
        parts.append(f"## Your previous attempt (turn {turn - 1})\n```diff\n{prev_diff or '(no applicable edits)'}\n```")
        parts.append(f"## What happened\n{prev_feedback}\nWrite a complete new set of edits against the ORIGINAL files above.")
    return "\n\n".join(parts)


def _feedback(rep) -> str:
    if rep.timed_out:
        return "The test run timed out. Your change probably introduced an infinite loop or very slow code."
    if rep.crashed:
        return "The test suite could not run at all (import or syntax error?).\n```\n" + rep.output[-1500:] + "\n```"
    lines = [f"{rep.passed}/{rep.total} tests pass. Still failing:"]
    lines += [f"- {t}" for t in rep.failing[:12]]
    lines.append("```\n" + rep.output[-1800:] + "\n```")
    return "\n".join(lines)


def run_contestant(ctx: RaceContext, c: Contestant) -> Outcome:
    out = Outcome(cid=c.id)
    started = time.monotonic()
    emit = ctx.emit
    model = model_for(c.tier)
    prev_diff, prev_feedback = "", ""
    last_timeout = False

    def finish(status: str, reason: str = "") -> Outcome:
        out.status, out.reason = status, reason
        out.elapsed = round(time.monotonic() - started, 2)
        out.cost = round(cost_usd(c.tier, out.tokens_in, out.tokens_out), 6)
        emit("c.done", cid=c.id, status=status, reason=reason, turns=out.turns, elapsed=out.elapsed,
             cost=out.cost, tokens_in=out.tokens_in, tokens_out=out.tokens_out,
             added=out.added, removed=out.removed, passed=out.passed, total=out.total)
        return out

    for turn in range(1, ctx.max_turns + 1):
        if ctx.cancel.is_set():
            return finish("cancelled", "another contestant already won")
        out.turns = turn
        emit("c.stage", cid=c.id, stage="thinking", turn=turn)
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _user_prompt(ctx, c, turn, prev_diff, prev_feedback)},
        ]
        try:
            res = ctx.llm.complete(model=model, messages=messages, temperature=c.temperature,
                                   max_tokens=4096, role="patch", cid=c.id, turn=turn)
        except LLMError as exc:
            return finish("error", str(exc))
        out.tokens_in += res.tokens_in
        out.tokens_out += res.tokens_out
        emit("c.llm", cid=c.id, turn=turn, tokens_in=res.tokens_in, tokens_out=res.tokens_out,
             latency=round(res.latency, 2), cost=round(cost_usd(c.tier, out.tokens_in, out.tokens_out), 6))
        if ctx.cancel.is_set():
            return finish("cancelled", "another contestant already won")

        emit("c.stage", cid=c.id, stage="patching", turn=turn)
        edits = parse_edits(res.text)
        if not edits:
            prev_diff, prev_feedback = "", "Your reply contained no valid edit blocks. Use the FILE / SEARCH / REPLACE format exactly."
            emit("c.edit", cid=c.id, turn=turn, diff="", files=[], added=0, removed=0, error=prev_feedback)
            continue

        ws = copy_repo(ctx.pristine, ctx.scratch / f"{c.id}-t{turn}")
        applied = apply_edits(ws, edits)
        if applied.errors:
            prev_diff, prev_feedback = "", "Some edits could not be applied:\n" + "\n".join(f"- {e}" for e in applied.errors)
            emit("c.edit", cid=c.id, turn=turn, diff="", files=applied.changed, added=0, removed=0,
                 error="; ".join(applied.errors))
            shutil.rmtree(ws, ignore_errors=True)
            continue

        touched = [p for p in applied.changed if is_protected(p)]
        diff = make_diff(ctx.pristine, ws, applied.changed)
        added, removed = diff_stats(diff)
        out.diff, out.added, out.removed, out.files = diff, added, removed, applied.changed
        emit("c.edit", cid=c.id, turn=turn, diff=diff, files=applied.changed, added=added, removed=removed, error="")
        if touched:
            shutil.rmtree(ws, ignore_errors=True)
            return finish("disqualified", f"modified protected files: {', '.join(touched)}")

        emit("c.stage", cid=c.id, stage="testing", turn=turn)
        rep = ctx.runner.run_tests(ws, ctx.test_cmd, ctx.timeout)
        out.passed, out.total = rep.passed, rep.total
        emit("c.tests", cid=c.id, turn=turn, passed=rep.passed, failed=rep.failed + rep.errors, total=rep.total,
             failing=rep.failing, timed_out=rep.timed_out, crashed=rep.crashed,
             output=rep.output[-1500:], duration=rep.duration)

        collected_all = rep.total == ctx.baseline_total
        if rep.green and collected_all:
            out.workspace = ws
            return finish("passed")
        last_timeout = rep.timed_out
        prev_diff = diff
        prev_feedback = _feedback(rep) if collected_all else (
            f"The suite now collects {rep.total} tests but {ctx.baseline_total} existed before. Do not remove or skip tests.")
        shutil.rmtree(ws, ignore_errors=True)

    return finish("timeout" if last_timeout else "failed", "out of attempts")
