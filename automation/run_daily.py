#!/usr/bin/env python3
"""Cloud + local entrypoint. Mac can be off — GitHub Actions + Late still publish."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from workflow_one import load_config, load_dotenv  # noqa: E402

load_dotenv(HERE / ".env")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default=os.environ.get("KIND", "auto"))
    ap.add_argument("--when", default=os.environ.get("WHEN") or None)
    ap.add_argument("--one", action="store_true", help="Only the next remaining slot")
    ap.add_argument("--spotlight", help="Paste a YouTube/X/article URL and post about that clip")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--every-hours", type=float, default=4)
    ap.add_argument(
        "--live",
        action="store_true",
        default=os.environ.get("LIVE", "").lower() in {"1", "true", "yes"},
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    live = args.live and not args.dry_run
    print("EagleEye daily runner")
    print("  LATE_API_KEY", "set" if os.environ.get("LATE_API_KEY", "").strip() else "MISSING")
    print("  XAI_API_KEY", "set" if os.environ.get("XAI_API_KEY", "").strip() else "MISSING")
    print("  GITHUB_ACTIONS", os.environ.get("GITHUB_ACTIONS") or "false")
    print("  live", live)
    # One publisher: GitHub Actions is the clock. Mac launchd must not also post.
    # Dashboard "Run" sets ALLOW_LOCAL_LIVE=1 for a manual shot.
    local_ok = os.environ.get("ALLOW_LOCAL_LIVE", "").lower() in {"1", "true", "yes"}
    if live and not os.environ.get("GITHUB_ACTIONS") and not local_ok:
        print("STOP       local auto-post is off. GitHub Actions is the publisher.")
        print("           Dashboard Run / Spotlight still work (they set ALLOW_LOCAL_LIVE).")
        return
    from engine import notify_if_ended, remaining_slots, run_once, run_spotlight

    cfg = load_config()
    if notify_if_ended(cfg):
        return
    if args.spotlight:
        print("  spotlight", args.spotlight, "x", args.count, "every", args.every_hours, "h")
        run_spotlight(args.spotlight, args.count, args.every_hours, live)
        return
    one = args.one or os.environ.get("ONE", "").lower() in {"1", "true", "yes"}
    slots = remaining_slots(cfg, args.when or None, one=one)
    cap = max(1, int(cfg.get("max_posts_per_run") or 4))
    slots = slots[:cap]
    deadline = time.time() + max(60, int(cfg.get("max_runtime_sec") or 900))
    max_fail = max(1, int(cfg.get("max_failures_per_run") or 3))
    print("  slots    ", slots)
    print("  cap      ", cap, "runtime_s", int(deadline - time.time()), "max_fail", max_fail)
    if not slots:
        print("STOP       no free slots (already booked in Late or local state)")
        return None
    last = None
    fails = 0
    ok_n = 0
    for when in slots:
        if time.time() > deadline:
            print("STOP       runtime cap — not posting more this run")
            break
        try:
            last = run_once(args.kind, when, live)
            st = (last or {}).get("status") or ""
            if st in {"ended"}:
                break
            if st in {"scheduled", "published", "submitted"}:
                ok_n += 1
            elif live and st not in {"already-posted", "skipped-day", "dry-run"}:
                fails += 1
        except Exception as e:  # noqa: BLE001
            print("FAIL      ", e)
            fails += 1
        if fails >= max_fail:
            print("STOP       too many failures this run")
            break
        time.sleep(1)
    print("  result   scheduled", ok_n, "fails", fails)
    if live and ok_n == 0 and fails:
        sys.exit(1)
    return last


if __name__ == "__main__":
    main()
