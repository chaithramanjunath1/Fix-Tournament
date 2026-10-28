"""Open a pull request with the winning patch.

Untested against live GitHub in the build environment: it needs a token with
write access to the repository (or a fork you own). Failures are reported as
RuntimeError with the underlying message so the UI can show them.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import httpx


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {p.stderr.strip()[-300:]}")
    return p.stdout.strip()


def open_pull_request(repo_url: str, patch: str, title: str, body: str, token: str, branch: str) -> str:
    m = re.match(r"https://github\.com/([^/]+)/([^/.]+)", repo_url)
    if not m:
        raise RuntimeError("only github.com repositories are supported")
    owner, repo = m.group(1), m.group(2)
    with tempfile.TemporaryDirectory(prefix="ft-pr-") as tmp:
        work = Path(tmp) / "repo"
        authed = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        _git(Path(tmp), "clone", "--depth", "1", authed, str(work))
        base = _git(work, "rev-parse", "--abbrev-ref", "HEAD")
        _git(work, "checkout", "-b", branch)
        patch_file = Path(tmp) / "fix.patch"
        patch_file.write_bytes(patch.encode("utf-8"))
        _git(work, "apply", str(patch_file))
        _git(work, "-c", "user.name=Fix Tournament", "-c", "user.email=fix-tournament@users.noreply.github.com",
             "commit", "-am", title)
        _git(work, "push", "origin", branch)
    r = httpx.post(f"https://api.github.com/repos/{owner}/{repo}/pulls", timeout=30,
                   headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                   json={"title": title, "head": branch, "base": base, "body": body})
    if r.status_code >= 300:
        raise RuntimeError(f"GitHub refused the pull request: {r.status_code} {r.text[:200]}")
    return r.json()["html_url"]
