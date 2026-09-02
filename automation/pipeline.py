#!/usr/bin/env python3
"""
EagleEye social pipeline.

Kinds: eagleeye | golf-world | text
Flow: pick kind → write copy → (optional) generate still → upload to Late media → schedule post.

Usage:
  python3 pipeline.py --dry-run
  python3 pipeline.py --kind eagleeye --when "2026-09-02 09:30"
  python3 pipeline.py --kind golf-world --when "2026-09-02 12:15"
  python3 pipeline.py              # uses cadence for America/New_York now+
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path):  # noqa: ARG001
        if not Path(path).exists():
            return
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
load_dotenv(HERE / ".env")

TZ = ZoneInfo("America/New_York")
STORE = "https://apps.apple.com/app/id6793305657"
LATE_BASE = "https://getlate.dev/api/v1"


def load_config() -> dict:
    path = HERE / "config.json"
    if not path.exists():
        path = HERE / "config.example.json"
    return json.loads(path.read_text())


def load_bank(rel: str) -> list[dict]:
    p = (HERE / rel).resolve()
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def next_unused(rows: list[dict], used_ids: set[str]) -> dict:
    for r in rows:
        if r["id"] not in used_ids:
            return r
    return rows[0]


def used_log_ids() -> set[str]:
    log = HERE / "logs" / "posts.csv"
    if not log.exists():
        return set()
    with log.open(newline="", encoding="utf-8") as f:
        return {r.get("bank_id", "") for r in csv.DictReader(f)}


def last_kinds(n: int = 2) -> list[str]:
    log = HERE / "logs" / "posts.csv"
    if not log.exists():
        return []
    with log.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r["kind"] for r in rows[-n:]]


def pick_kind(cfg: dict, override: str | None) -> str:
    if override:
        return override
    wd = datetime.now(TZ).weekday()
    for slot in cfg["cadence"]:
        if int(slot["weekday"]) == wd:
            kind = slot["kind"]
            break
    else:
        kind = "golf-world"
    if cfg.get("never_two_product_in_a_row") and kind == "eagleeye":
        if last_kinds(1) == ["eagleeye"]:
            kind = "golf-world"
    return kind


def clip_x(text: str, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def grok_copy(kind: str, seed: dict) -> str:
    """Optional rewrite. Default is the bank copy (already on-voice)."""
    return seed["copy"].strip()


def late_headers() -> dict:
    key = os.environ.get("LATE_API_KEY", "")
    if not key:
        raise SystemExit("Missing LATE_API_KEY in automation/.env")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def late_presign_and_upload(image_path: Path) -> str:
    import json as _json
    import urllib.request

    body = _json.dumps({"filename": image_path.name, "contentType": "image/jpeg"}).encode()
    req = urllib.request.Request(
        f"{LATE_BASE}/media/presign",
        data=body,
        headers=late_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = _json.loads(resp.read().decode())
    upload_url = data.get("uploadUrl") or data.get("upload_url")
    public_url = data.get("publicUrl") or data.get("public_url")
    if not upload_url or not public_url:
        raise SystemExit(f"Unexpected presign response: {data}")
    img = image_path.read_bytes()
    put = urllib.request.Request(
        upload_url,
        data=img,
        method="PUT",
        headers={"Content-Type": "image/jpeg"},
    )
    with urllib.request.urlopen(put):
        pass
    return public_url


def late_create_post(payload: dict) -> dict:
    import json as _json
    import urllib.request

    req = urllib.request.Request(
        f"{LATE_BASE}/posts",
        data=_json.dumps(payload).encode(),
        headers=late_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return _json.loads(resp.read().decode())


def platform_list(kind: str, cfg: dict) -> list[dict]:
    names = cfg["platforms_text"] if kind == "text" else cfg["platforms_stills"]
    mapping = {
        "twitter": os.environ.get("LATE_TWITTER_ACCOUNT_ID", ""),
        "instagram": os.environ.get("LATE_INSTAGRAM_ACCOUNT_ID", ""),
        "reddit": os.environ.get("LATE_REDDIT_ACCOUNT_ID", ""),
        "facebook": os.environ.get("LATE_FACEBOOK_ACCOUNT_ID", ""),
    }
    out = []
    for name in names:
        acc = mapping.get(name)
        if not acc:
            continue
        item: dict = {"platform": name, "accountId": acc}
        if name == "instagram":
            item["platformSpecificData"] = {
                "contentType": "post",
                "firstComment": f"Download on the App Store: {STORE}",
            }
        if name == "reddit":
            item["platformSpecificData"] = {
                "subreddit": cfg.get("reddit_subreddit", "u_eagleeyegolfapp")
            }
        out.append(item)
    if not out:
        raise SystemExit("No Late account IDs in .env — fill LATE_*_ACCOUNT_ID")
    return out


def append_log(row: dict) -> None:
    log = HERE / "logs" / "posts.csv"
    log.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "ts",
        "kind",
        "bank_id",
        "schedule_time",
        "copy",
        "media_url",
        "late_id",
        "status",
    ]
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def parse_when(s: str | None) -> str:
    if not s:
        now = datetime.now(TZ)
        dt = now.replace(second=0, microsecond=0)
        if dt.minute not in (0, 30):
            dt = dt + timedelta(minutes=(30 - dt.minute % 30))
        if dt <= now:
            dt += timedelta(minutes=30)
        return dt.strftime("%Y-%m-%d %H:%M")
    return s


def run(kind: str, when: str, dry: bool, image: Path | None, cfg: dict) -> None:
    banks = cfg["banks"]
    seed = next_unused(load_bank(banks[kind]), used_log_ids())
    copy = clip_x(grok_copy(kind, seed), cfg.get("x_max_chars", 280))
    media_url = ""
    image_path = image

    if kind != "text":
        if image_path is None:
            # Bank rows are briefs. For fully auto image gen, call xAI Imagine here.
            # Test posts pass --image.
            raise SystemExit(
                f"Kind {kind} needs an image. Pass --image PATH "
                "(or wire XAI Imagine in generate_image())."
            )
        if dry:
            media_url = f"file://{image_path}"
        else:
            media_url = late_presign_and_upload(image_path)

    platforms = (
        [{"platform": p, "accountId": "DRY"} for p in (cfg["platforms_text"] if kind == "text" else cfg["platforms_stills"])]
        if dry
        else platform_list(kind, cfg)
    )

    payload = {
        "content": copy,
        "timezone": cfg["timezone"],
        "scheduledFor": when.replace(" ", "T") if "T" not in when else when,
        "platforms": platforms,
    }
    if media_url and not dry:
        payload["mediaItems"] = [{"url": media_url, "type": "image"}]
    if kind == "text":
        payload.pop("mediaItems", None)

    print("KIND     ", kind)
    print("WHEN     ", when, cfg["timezone"])
    print("BANK ID  ", seed["id"])
    print("COPY     ", copy)
    print("IMAGE    ", image_path or "(none)")
    print("MEDIA URL", media_url or "(none)")
    print("PLATFORMS", [p["platform"] for p in platforms])

    late_id, status = "", "dry-run"
    if not dry:
        res = late_create_post(payload)
        post = res.get("post") or res
        late_id = str(post.get("_id") or post.get("id") or "")
        status = str(post.get("status") or "submitted")
        print("LATE     ", late_id, status)

    append_log(
        {
            "ts": datetime.now(TZ).isoformat(timespec="seconds"),
            "kind": kind,
            "bank_id": seed["id"],
            "schedule_time": when,
            "copy": copy,
            "media_url": media_url,
            "late_id": late_id,
            "status": status,
        }
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["eagleeye", "golf-world", "text"])
    ap.add_argument("--when", help='Local time "YYYY-MM-DD HH:MM"')
    ap.add_argument("--image", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    kind = pick_kind(cfg, args.kind)
    when = parse_when(args.when)
    run(kind, when, args.dry_run, args.image, cfg)


if __name__ == "__main__":
    main()
