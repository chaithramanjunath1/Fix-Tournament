"""Builds a Tournament from a request. Shared by the web server and the CLI."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from .agent import build_roster
from .cases import load_case
from .config import Settings
from .llm import NebiusClient, ReplayClient
from .runners import make_runner
from .tournament import EventLog, Spec, Tournament


class RequestError(ValueError):
    pass


def _clone(url: str, dest: Path) -> Path:
    if not url.startswith("https://"):
        raise RequestError("Only https:// repository URLs are supported.")
    proc = subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RequestError(f"git clone failed: {proc.stderr.strip()[-300:]}")
    return dest


def _fetch_issue(issue_url: str, token: str = "") -> tuple[str, str]:
    """Fetch a public GitHub issue as (title, body)."""
    import re
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)", issue_url)
    if not m:
        raise RequestError("Issue URL must look like https://github.com/<owner>/<repo>/issues/<n>")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = httpx.get(f"https://api.github.com/repos/{m[1]}/{m[2]}/issues/{m[3]}", headers=headers, timeout=20)
    if r.status_code != 200:
        raise RequestError(f"GitHub returned {r.status_code} for that issue.")
    data = r.json()
    return data["title"], data.get("body") or ""


def create_tournament(settings: Settings, req: dict, log: EventLog) -> Tournament:
    source = req.get("source", "auto")
    if source == "auto":
        source = "live" if settings.live_available and not settings.force_replay else "replay"
    size = int(req.get("size", 8))
    mode = req.get("mode", "qualify")
    if mode not in ("qualify", "sprint"):
        raise RequestError("mode must be 'qualify' or 'sprint'")

    custom = bool(req.get("repo_url"))
    if custom:
        if not settings.allow_custom:
            raise RequestError("Custom repositories are disabled on this server (set FT_ALLOW_CUSTOM=1).")
        if source != "live":
            raise RequestError("Custom repositories need live mode: set NEBIUS_API_KEY.")
        work = Path(tempfile.mkdtemp(prefix="ft-clone-"))
        repo = _clone(req["repo_url"], work / "repo")
        if req.get("issue_url"):
            title, body = _fetch_issue(req["issue_url"], settings.github_token)
        else:
            title, body = req.get("issue_title", "Failing tests"), req.get("issue_text", "Make the failing tests pass.")
        spec = Spec(repo=repo, issue_text=f"{title}\n\n{body}", issue_title=title,
                    test_cmd=req.get("test_cmd") or "pytest -q", timeout=settings.test_timeout, case_title=req["repo_url"])
        script = None
    else:
        case = load_case(req.get("case", "slugger"))
        spec = Spec(repo=case.repo, issue_text=case.issue_text, issue_title=case.issue_title,
                    test_cmd=case.test_cmd, timeout=case.timeout, case_title=case.title)
        script = case.script

    if source == "live":
        if not settings.live_available:
            raise RequestError("Live mode needs NEBIUS_API_KEY.")
        llm = NebiusClient(settings.base_url, settings.api_key)
    else:
        if script is None:
            raise RequestError("This case has no replay script.")
        llm = ReplayClient(script, settings.replay_speed)

    runner = make_runner(settings.runner, settings.job_cmd)
    return Tournament(spec, llm, runner, build_roster(size), mode, log, max_turns=settings.max_turns)
