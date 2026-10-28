"""CLI: `python -m fixtournament serve` or `python -m fixtournament run --case slugger`."""

from __future__ import annotations

import argparse
import sys
import threading
import time

from .config import load_settings
from .service import RequestError, create_tournament
from .tournament import EventLog


def _run(args) -> int:
    settings = load_settings()
    log = EventLog()
    try:
        t = create_tournament(settings, {"case": args.case, "size": args.size, "mode": args.mode,
                                         "source": args.source, "repo_url": args.repo, "issue_url": args.issue,
                                         "test_cmd": args.test_cmd}, log)
    except RequestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    th = threading.Thread(target=t.run, daemon=True)
    th.start()
    seen = 0
    while th.is_alive() or seen < len(log.events):
        while seen < len(log.events):
            ev = log.events[seen]
            seen += 1
            _print(ev)
        time.sleep(0.05)
    if t.result is None:
        return 1
    if args.patch and t.patch:
        open(args.patch, "w", encoding="utf-8", newline="\n").write(t.patch)
        print(f"\npatch written to {args.patch}")
    return 0


def _print(ev: dict) -> None:
    kind, t = ev["type"], f"{ev['t']:6.1f}s"
    if kind == "phase":
        print(f"{t}  == {ev['phase'].upper()}")
    elif kind == "reproduce.result":
        print(f"{t}  reproduced: {len(ev['failing'])} failing of {ev['total']}")
    elif kind == "diagnose.result":
        print(f"{t}  diagnosis ready ({ev['model']})")
    elif kind == "c.done":
        print(f"{t}  {ev['cid']:<16} {ev['status']:<12} turns={ev['turns']} +{ev['added']}/-{ev['removed']} {ev['reason']}")
    elif kind == "verify.result":
        print(f"{t}  verify {ev['cid']}: {'stable' if ev['stable'] else 'FLAKY'}")
    elif kind == "result":
        w = ev["winner"]
        print(f"{t}  winner: {w}")
        for r in ev["ranking"]:
            print(f"        #{r['rank']} {r['cid']:<16} {r['status']:<12} score={r['score']}")
        c = ev["costs"]
        print(f"        cost (est.): routed ${c['routed']:.4f} vs all-Ultra ${c['all_ultra']:.4f}")
    elif kind == "error":
        print(f"{t}  ERROR: {ev['message']}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="fixtournament")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    r = sub.add_parser("run", help="run one tournament in the terminal")
    r.add_argument("--case", default="slugger")
    r.add_argument("--size", type=int, default=8)
    r.add_argument("--mode", default="qualify", choices=["qualify", "sprint"])
    r.add_argument("--source", default="auto", choices=["auto", "live", "replay"])
    r.add_argument("--repo")
    r.add_argument("--issue")
    r.add_argument("--test-cmd")
    r.add_argument("--patch", help="write the winning patch to this file")
    args = ap.parse_args()
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("fixtournament.server:app", host=args.host, port=args.port, log_level="info")
        return 0
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
