"""FastAPI app: starts tournaments and streams their event log over SSE."""

from __future__ import annotations

import asyncio
import json
import secrets
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .cases import list_cases
from .config import TIERS, WEB_DIR, load_settings, model_for
from .service import RequestError, create_tournament
from .tournament import EventLog, Tournament

settings = load_settings()
app = FastAPI(title="Fix Tournament", version=__version__)


@dataclass
class Run:
    id: str
    log: EventLog
    tournament: Tournament
    request: dict
    thread: threading.Thread | None = None
    finished: bool = False
    repo_url: str = ""


RUNS: dict[str, Run] = {}
MAX_RUNS_KEPT = 40
_active = threading.Semaphore(3)


def _drive(run: Run) -> None:
    with _active:
        try:
            run.tournament.run()
        finally:
            run.finished = True


@app.get("/api/config")
def config():
    return {
        "version": __version__,
        "live_available": settings.live_available and not settings.force_replay,
        "default_source": "live" if settings.live_available and not settings.force_replay else "replay",
        "runner": settings.runner,
        "allow_custom": settings.allow_custom,
        "can_open_pr": bool(settings.github_token),
        "max_turns": settings.max_turns,
        "tiers": {k: {"label": v["label"], "model": model_for(k)} for k, v in TIERS.items()},
        "cases": [c.public() for c in list_cases()],
    }


@app.post("/api/runs")
async def start_run(request: Request):
    try:
        req = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "body must be JSON")
    log = EventLog()
    try:
        tournament = await asyncio.to_thread(create_tournament, settings, req, log)
    except RequestError as exc:
        raise HTTPException(400, str(exc))
    except KeyError as exc:
        raise HTTPException(400, f"unknown case: {exc}")
    except FileNotFoundError:
        raise HTTPException(400, "unknown case")
    run = Run(id=secrets.token_urlsafe(6), log=log, tournament=tournament, request=req,
              repo_url=req.get("repo_url", ""))
    RUNS[run.id] = run
    while len(RUNS) > MAX_RUNS_KEPT:
        RUNS.pop(next(iter(RUNS)))
    run.thread = threading.Thread(target=_drive, args=(run,), daemon=True)
    run.thread.start()
    return {"run_id": run.id}


def _get(run_id: str) -> Run:
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    return run


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str, request: Request, last: int = -1):
    run = _get(run_id)

    async def stream():
        i = last + 1
        idle = 0
        while True:
            sent = False
            while i < len(run.log.events):
                ev = run.log.events[i]
                i += 1
                sent = True
                yield f"id: {ev['seq']}\ndata: {json.dumps(ev)}\n\n"
            if run.finished and i >= len(run.log.events):
                yield "event: end\ndata: {}\n\n"
                return
            if await request.is_disconnected():
                return
            idle = 0 if sent else idle + 1
            if idle and idle % 150 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.07)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id: str):
    _get(run_id).tournament.stop()
    return {"ok": True}


@app.get("/api/runs/{run_id}/patch")
def patch(run_id: str):
    run = _get(run_id)
    if not run.tournament.patch:
        raise HTTPException(404, "no patch yet")
    return PlainTextResponse(run.tournament.patch, headers={
        "Content-Disposition": f'attachment; filename="fix-tournament-{run_id}.patch"'})


@app.post("/api/runs/{run_id}/pr")
def open_pr(run_id: str):
    """Push the winning patch to a branch and open a pull request (custom repos, needs FT_GITHUB_TOKEN
    with write access to the repository)."""
    run = _get(run_id)
    t = run.tournament
    if not (t.result and t.patch):
        raise HTTPException(409, "no winning patch to submit")
    if not run.repo_url or not settings.github_token:
        raise HTTPException(400, "PRs need a custom GitHub repo and FT_GITHUB_TOKEN")
    from .github import open_pull_request
    try:
        url = open_pull_request(run.repo_url, t.patch, t.result["pr"]["title"], t.result["pr"]["body"],
                                settings.github_token, f"fix-tournament/{run.id}")
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    return {"url": url}


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
