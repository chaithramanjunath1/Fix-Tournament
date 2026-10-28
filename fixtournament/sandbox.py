"""Workspaces and test execution.

`run_tests` runs pytest in a child process with a wall-clock timeout, resource
limits and a scrubbed environment, and reads results from a junit XML file so
pass/fail is per test, not scraped from console text.

Isolation note: this is process-level isolation (own process group, rlimits,
throwaway copy of the repo). It is not a network sandbox. For untrusted code,
run the same worker inside a container, which is what the Nebius Serverless
Job runner is for (see runners.py).
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", "*.pyc", ".mypy_cache", ".ruff_cache"
)


@dataclass
class TestReport:
    __test__ = False  # not a pytest class

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0
    passing: list[str] = field(default_factory=list)
    failing: list[str] = field(default_factory=list)
    output: str = ""
    duration: float = 0.0
    timed_out: bool = False
    crashed: bool = False

    @property
    def green(self) -> bool:
        return (
            not self.timed_out
            and not self.crashed
            and self.failed == 0
            and self.errors == 0
            and self.total > 0
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TestReport":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def copy_repo(src: Path, dst: Path) -> Path:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=IGNORE)
    return dst


def _limits(timeout: float):
    def apply():
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (int(timeout) + 3, int(timeout) + 3))
            resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
            if sys.platform.startswith("linux"):
                resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
        except Exception:
            pass

    return apply


def _child_env(root: Path) -> dict:
    """Minimal environment for the test process.

    On Windows Python needs SYSTEMROOT (and friends) just to start, so keep the
    OS essentials there; on POSIX the environment is fully scrubbed.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(root),
        "LANG": "C.UTF-8",
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": "",
    }
    if os.name == "nt":
        for k in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
                  "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "NUMBER_OF_PROCESSORS"):
            if k in os.environ:
                env[k] = os.environ[k]
    return env


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=15)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, OSError, subprocess.SubprocessError):
        proc.kill()


def _argv(cmd: str | list[str] | None) -> list[str]:
    if not cmd:
        return [sys.executable, "-m", "pytest", "-q"]
    parts = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    if parts and parts[0] in ("pytest", "py.test"):
        parts = [sys.executable, "-m", "pytest", *parts[1:]]
    return parts


def _parse_junit(path: Path) -> tuple[list[str], list[str], dict]:
    passing, failing = [], []
    counts = {"failed": 0, "errors": 0, "skipped": 0}
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        tid = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        kids = {child.tag for child in case}
        if "failure" in kids:
            failing.append(tid)
            counts["failed"] += 1
        elif "error" in kids:
            failing.append(tid)
            counts["errors"] += 1
        elif "skipped" in kids:
            counts["skipped"] += 1
        else:
            passing.append(tid)
    return passing, failing, counts


def run_tests(root: Path | str, cmd: str | list[str] | None = None, timeout: float = 30.0) -> TestReport:
    root = Path(root)
    scratch = Path(tempfile.mkdtemp(prefix="ft-junit-"))
    xml_path = scratch / "report.xml"
    argv = _argv(cmd) + ["-p", "no:cacheprovider", f"--junitxml={xml_path}"]
    env = _child_env(root)
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(
            argv,
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=(os.name != "nt"),
            preexec_fn=_limits(timeout) if os.name == "posix" else None,
        )
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            out, _ = proc.communicate()
    except OSError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        return TestReport(output=f"could not start test command: {exc}", crashed=True)

    duration = time.monotonic() - started
    out = (out or "")[-6000:]
    report = TestReport(output=out, duration=round(duration, 2), timed_out=timed_out)
    if xml_path.exists() and not timed_out:
        try:
            passing, failing, counts = _parse_junit(xml_path)
            report.passing, report.failing = passing, failing
            report.passed = len(passing)
            report.failed, report.errors, report.skipped = counts["failed"], counts["errors"], counts["skipped"]
            report.total = len(passing) + len(failing)
        except ET.ParseError:
            report.crashed = True
    else:
        report.crashed = not timed_out
    # Collection errors (e.g. ImportError) produce an <error> testcase, but be defensive.
    if report.total == 0 and not timed_out:
        report.crashed = True
    shutil.rmtree(scratch, ignore_errors=True)
    return report
