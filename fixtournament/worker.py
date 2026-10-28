"""Container entrypoint: run a candidate workspace's tests and print a TestReport.

Reads the JSON payload from stdin (see runners.py), unpacks the tarball into a
fresh temp directory, runs the tests and prints the report as the last line of
stdout. This is the process that runs inside each Nebius Serverless Job, one job
per candidate, so the parallelism on the scoreboard is real compute.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import tarfile
import tempfile
from pathlib import Path

from .sandbox import run_tests


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest.resolve())) or member.issym() or member.islnk():
            raise ValueError(f"unsafe path in archive: {member.name}")
    tar.extractall(dest)


def main() -> int:
    payload = json.load(sys.stdin)
    with tempfile.TemporaryDirectory(prefix="ft-worker-") as tmp:
        dest = Path(tmp)
        raw = base64.b64decode(payload["tar_b64"])
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            _safe_extract(tar, dest)
        report = run_tests(dest, payload.get("cmd"), float(payload.get("timeout", 30)))
    print(json.dumps(report.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
