import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

from fixtournament.agent import build_roster
from fixtournament.analysis import blast_radius
from fixtournament.cases import load_case
from fixtournament.llm import ReplayClient
from fixtournament.patching import apply_edits, is_protected, parse_edits
from fixtournament.runners import JobRunner, LocalRunner
from fixtournament.sandbox import copy_repo, run_tests
from fixtournament.tournament import EventLog, Spec, Tournament


def block(path, search, replace):
    return f"FILE: {path}\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\n"


# ---------- patching ----------
def test_parse_and_apply(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    edits = parse_edits("note\n" + block("a.py", "x = 1", "x = 10"))
    assert len(edits) == 1
    res = apply_edits(tmp_path, edits)
    assert res.changed == ["a.py"] and not res.errors
    assert (tmp_path / "a.py").read_text() == "x = 10\ny = 2\n"


def test_ambiguous_and_missing_search_are_rejected(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n")
    assert apply_edits(tmp_path, parse_edits(block("a.py", "x = 1", "x = 2"))).errors
    assert apply_edits(tmp_path, parse_edits(block("a.py", "nope", "x"))).errors
    assert (tmp_path / "a.py").read_text() == "x = 1\nx = 1\n"


def test_path_escape_is_rejected(tmp_path):
    res = apply_edits(tmp_path, parse_edits(block("../evil.py", "", "boom")))
    assert res.errors and not (tmp_path.parent / "evil.py").exists()


def test_trailing_whitespace_tolerated(tmp_path):
    (tmp_path / "a.py").write_text("x = 1   \ny = 2\n")
    res = apply_edits(tmp_path, parse_edits(block("a.py", "x = 1", "x = 9")))
    assert not res.errors and (tmp_path / "a.py").read_text().startswith("x = 9")


@pytest.mark.parametrize("p,expected", [
    ("tests/test_core.py", True), ("conftest.py", True), ("pkg/test_x.py", True),
    ("pytest.ini", True), ("pkg/core.py", False), ("pkg/testing_utils.py", False),
])
def test_protected_paths(p, expected):
    assert is_protected(p) is expected


# ---------- sandbox ----------
def test_run_tests_reports_per_test(tmp_path):
    case = load_case("slugger")
    ws = copy_repo(case.repo, tmp_path / "w")
    rep = run_tests(ws, "pytest -q", 20)
    assert rep.total == 13 and rep.failed == 4 and not rep.green
    assert any("trims_separators" in t for t in rep.failing)


def test_timeout_kills_runaway(tmp_path):
    (tmp_path / "test_loop.py").write_text("def test_x():\n    while True:\n        pass\n")
    rep = run_tests(tmp_path, "pytest -q", 2)
    assert rep.timed_out and not rep.green


def test_collection_error_is_not_green(tmp_path):
    (tmp_path / "test_bad.py").write_text("import does_not_exist\n")
    rep = run_tests(tmp_path, "pytest -q", 10)
    assert not rep.green


def test_job_runner_protocol_matches_local(tmp_path):
    case = load_case("slugger")
    ws = copy_repo(case.repo, tmp_path / "w")
    job = JobRunner([sys.executable, "-m", "fixtournament.worker"])
    a, b = job.run_tests(ws, "pytest -q", 20), LocalRunner().run_tests(ws, "pytest -q", 20)
    assert (a.total, a.failed, sorted(a.failing)) == (b.total, b.failed, sorted(b.failing))


# ---------- analysis ----------
def test_blast_radius_counts_callers(tmp_path):
    case = load_case("slugger")
    new = copy_repo(case.repo, tmp_path / "n")
    p = new / "slugger/core.py"
    p.write_text(p.read_text().replace("text = text[:max_length]", "text = text[:max_length].strip(sep)"))
    out = blast_radius(case.repo, new, ["slugger/core.py"])
    assert out and out[0]["symbol"] == "slugify"
    assert len(out[0]["production"]) == 1 and len(out[0]["tests"]) >= 10


# ---------- full tournaments (replay, fast) ----------
def race(slug, size=8, mode="qualify"):
    case = load_case(slug)
    log = EventLog()
    spec = Spec(case.repo, case.issue_text, case.issue_title, case.test_cmd, case.timeout, case.title)
    t = Tournament(spec, ReplayClient(case.script, 0.02), LocalRunner(), build_roster(size), mode, log)
    return t, t.run(), log


@pytest.mark.parametrize("slug", ["slugger", "intervals"])
def test_full_race_picks_green_minimal_patch(slug):
    t, result, log = race(slug)
    assert result and result["winner"]
    rank = {r["cid"]: r for r in result["ranking"]}
    assert rank["nano-refactor"]["status"] == "disqualified"
    assert rank[result["winner"]]["status"] == "passed"
    assert result["patch"].startswith("--- a/")
    assert "test" not in result["patch"].split("\n")[0]
    # tiered routing must be cheaper than all-Ultra
    assert result["costs"]["routed"] < result["costs"]["all_ultra"]
    types = [e["type"] for e in log.events]
    assert types.index("reproduce.result") < types.index("diagnose.result") < types.index("verify.result") < types.index("result")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_winning_patch_really_fixes_the_repo(tmp_path):
    t, result, _ = race("slugger")
    ws = copy_repo(load_case("slugger").repo, tmp_path / "w")
    (tmp_path / "fix.patch").write_bytes(result["patch"].encode("utf-8"))
    import subprocess
    assert subprocess.run(["git", "apply", str(tmp_path / "fix.patch")], cwd=ws).returncode == 0
    assert run_tests(ws, "pytest -q", 20).green


def test_sprint_stops_the_field():
    t, result, log = race("slugger", mode="sprint")
    statuses = {r["status"] for r in result["ranking"]}
    assert "cancelled" in statuses or "passed" in statuses
    assert result["winner"]


def test_no_winner_is_reported_honestly():
    case = load_case("slugger")
    script = json.loads(json.dumps(case.script))  # copy
    for cid in script["contestants"]:
        script["contestants"][cid] = [(0.0, "I cannot fix this.")]
    log = EventLog()
    spec = Spec(case.repo, case.issue_text, case.issue_title, case.test_cmd, case.timeout, case.title)
    t = Tournament(spec, ReplayClient(script, 0), LocalRunner(), build_roster(4), "qualify", log, max_turns=2)
    result = t.run()
    assert result["winner"] is None and result["patch"] == ""
