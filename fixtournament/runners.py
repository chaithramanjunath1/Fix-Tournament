"""Where tests run.

LocalRunner executes pytest in-process-tree (fast, used for the demo).

JobRunner ships a tarball of the candidate workspace to an external command and
reads a TestReport back as JSON. The command is whatever submits and waits for a
containerised job, for example a script wrapping a Nebius Serverless Job. The
protocol is intentionally tiny so it can be exercised locally:

    stdin : {"tar_b64": "...", "cmd": "pytest -q" | null, "timeout": 20}
    stdout: last line is the TestReport JSON (see worker.py)

With FT_JOB_SUBMIT_CMD="python -m fixtournament.worker" the very same protocol
runs on this machine, which is how the test-suite covers it.
"""

from __future__ import annotations

import base64
import io
import json
import os
import shlex
import subprocess
import tarfile
from pathlib import Path

from .sandbox import IGNORE, TestReport, run_tests


class LocalRunner:
    name = "local"

    def run_tests(self, root: Path, cmd, timeout: float) -> TestReport:
        return run_tests(root, cmd, timeout)


def pack(root: Path) -> str:
    buf = io.BytesIO()
    skip = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"}
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(Path(root).rglob("*")):
            rel = p.relative_to(root)
            if any(part in skip for part in rel.parts) or p.suffix == ".pyc":
                continue
            tar.add(p, arcname=str(rel), recursive=False)
    return base64.b64encode(buf.getvalue()).decode()


def split_command(cmd) -> list[str]:
    """Split a command string; Windows paths keep their backslashes."""
    if isinstance(cmd, (list, tuple)):
        return list(cmd)
    if os.name == "nt":
        return [t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t
                for t in shlex.split(cmd, posix=False)]
    return shlex.split(cmd)


class JobRunner:
    name = "job"

    def __init__(self, submit_cmd):
        if not submit_cmd:
            raise ValueError("FT_JOB_SUBMIT_CMD is required when FT_RUNNER=job")
        self.argv = split_command(submit_cmd)

    def run_tests(self, root: Path, cmd, timeout: float) -> TestReport:
        payload = json.dumps({"tar_b64": pack(root), "cmd": cmd, "timeout": timeout})
        try:
            proc = subprocess.run(
                self.argv, input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout + 120,
            )
        except subprocess.TimeoutExpired:
            return TestReport(output="job did not return in time", timed_out=True)
        lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
        if proc.returncode != 0 or not lines:
            return TestReport(output=f"job failed ({proc.returncode}): {proc.stderr[-800:]}", crashed=True)
        try:
            return TestReport.from_dict(json.loads(lines[-1]))
        except (json.JSONDecodeError, TypeError):
            return TestReport(output=f"job returned unreadable output: {lines[-1][:300]}", crashed=True)


def make_runner(kind: str, job_cmd: str):
    if kind == "job":
        return JobRunner(job_cmd)
    return LocalRunner()
