"""CLI.

  python -m autopilot run            # one full cycle now (respects publish.dry_run)
  python -m autopilot tick           # run only if the schedule says a post is due (use from cron/Actions)
  python -m autopilot daemon         # loop forever on a server: tick every 10 minutes
  python -m autopilot scan           # competitor scan only, prints top videos
  python -m autopilot status         # schedule + last posts + scores
  python -m autopilot auth-youtube   # one-time: get YOUTUBE_REFRESH_TOKEN
  python -m autopilot auth-tiktok    # one-time: get TIKTOK_REFRESH_TOKEN
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback

from . import pipeline, scout
from .config import load_config, load_env, read_state


def main() -> int:
    ap = argparse.ArgumentParser(prog="autopilot")
    ap.add_argument("cmd", choices=["run", "tick", "daemon", "scan", "status", "auth-youtube", "auth-tiktok"])
    ap.add_argument("--config", default=None)
    ap.add_argument("--force-style", action="store_true", help="allow changing the locked channel style")
    ap.add_argument("--publish", action="store_true", help="override dry_run and upload")
    ap.add_argument("--dry-run", action="store_true", help="override config and never upload")
    a = ap.parse_args()

    load_env()
    cfg = load_config(a.config)
    dry = True if a.dry_run else (False if a.publish else None)

    if a.cmd == "run":
        pipeline.run(cfg, a.force_style, dry)
    elif a.cmd == "tick":
        due, why = pipeline.is_due(cfg)
        print(f"[tick] due={due} ({why})")
        if due:
            pipeline.run(cfg, a.force_style, dry)
    elif a.cmd == "daemon":
        print(f"[daemon] posting every {cfg['schedule']['interval_hours']}h")
        while True:
            try:
                cfg = load_config(a.config)
                due, why = pipeline.is_due(cfg)
                if due:
                    pipeline.run(cfg, a.force_style, dry)
            except Exception:
                traceback.print_exc()
            time.sleep(600)
    elif a.cmd == "scan":
        vids = scout.scan(cfg)
        print(scout.digest(vids, 30))
    elif a.cmd == "status":
        due, why = pipeline.is_due(cfg)
        print(f"style lock: {read_state('channel', {}).get('style', '(not locked yet)')} | config style: {cfg['channel']['style']}")
        print(f"interval: {cfg['schedule']['interval_hours']}h | due now: {due} ({why})")
        for h in read_state("history", [])[-10:]:
            flag = "POSTED" if h.get("posted") else "draft "
            v48 = h.get("views_48h")
            print(f"  {h['created_at'][:16]} {flag} score={h['virality']:5.1f} "
                  f"views48h={v48 if v48 is not None else '-':>7}  {h['title']}")
    elif a.cmd == "auth-youtube":
        from .publish import youtube
        youtube.interactive_auth()
    elif a.cmd == "auth-tiktok":
        from .publish import tiktok
        tiktok.interactive_auth()
    return 0


if __name__ == "__main__":
    sys.exit(main())
