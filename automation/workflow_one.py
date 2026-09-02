#!/usr/bin/env python3
"""
MACHINE A — golf-world news → official URLs → Late.

Does not download PGA TOUR / Golf Channel files. Discovers canonical
https URLs, writes golfer-voice copy, and packages an 84-col Late CSV
(and POST /v1/posts if LATE_API_KEY is set).

Usage:
  python3 workflow_one.py --dry-run
  python3 workflow_one.py --when "2026-09-02 18:20"
  python3 workflow_one.py --when "2026-09-02 18:20" --live
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(path):  # noqa: ARG001
        p = Path(path)
        if not p.exists():
            return
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DESKTOP = Path.home() / "Desktop"
load_dotenv(HERE / ".env")

TZ = ZoneInfo("America/New_York")
LATE_BASE = "https://getlate.dev/api/v1"
STILL = (
    "https://raw.githubusercontent.com/TheSgambini/eagleeyelabsllc"
    "/main/_late-media/test-golf-world-first-tee.jpg"
)
SAMPLE_CSV = HERE / "test_two_posts.csv"
UA = "EagleEyeGolf-Workflow1/1.0 (+https://eagleeyelabsllc.com/golf/)"

# Public pages we may cite. Never rip files from these.
ALLOWLIST = (
    "pgatour.com",
    "www.pgatour.com",
    "espn.com",
    "www.espn.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "golfdigest.com",
    "www.golfdigest.com",
    "apnews.com",
    "www.apnews.com",
)

# Verified 2026-08-30 TOUR Championship (PGA TOUR + ESPN). Used when
# live fetch confirms the same facts; never invent scores.
CANONICAL = {
    "id": "2026-08-30-tour-championship-scheffler",
    "headline": "Scottie Scheffler wins TOUR Championship, second FedExCup",
    "who": "Scottie Scheffler",
    "event": "TOUR Championship",
    "course": "East Lake",
    "when": "2026-08-30",
    "facts": {
        "sunday_score": "66",
        "to_par": "-16",
        "margin": "3",
        "runner_up": "Viktor Hovland",
        "fedex_cups": "2",
        "career_wins": "22",
        "started_sunday": "3 back",
    },
    "article_url": (
        "https://www.pgatour.com/article/news/daily-wrapup/2026/08/30/"
        "round-4-tour-championship-east-lake-golf-club-leaderboard-scores-results-storylines"
    ),
    "video_url": "https://www.youtube.com/watch?v=U3misH4gzvM",
    "video_title": (
        "Scottie Scheffler's SENSATIONAL Sunday to win FedExCup | "
        "Round 4 | TOUR Championship | 2026"
    ),
    "video_channel": "PGA TOUR",
    "still_url": STILL,
    "must_contain": ["Scheffler", "FedExCup", "East Lake"],
}


def load_config() -> dict:
    path = HERE / "config.json"
    if not path.exists():
        path = HERE / "config.example.json"
    return json.loads(path.read_text())


def csv_headers() -> list[str]:
    with SAMPLE_CSV.open(newline="", encoding="utf-8") as f:
        headers = next(csv.reader(f))
    if len(headers) != 84:
        raise SystemExit(f"Expected 84 Late columns, got {len(headers)}")
    return headers


def host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host_bare = host[4:]
    else:
        host_bare = host
    return host in ALLOWLIST or host_bare in ALLOWLIST


def twitter_len(text: str) -> int:
    return len(re.sub(r"https?://\S+", "x" * 23, text))


def http_get(url: str, timeout: int = 25) -> tuple[int, str]:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(800_000)
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.status, raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001
        print(f"GET failed {url}: {e}", file=sys.stderr)
        return 0, ""


def http_head_ok(url: str) -> bool:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            return 200 <= resp.status < 400
    except Exception:  # noqa: BLE001
        code, _ = http_get(url)
        return 200 <= code < 400


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data):  # noqa: ANN001
        if self._skip:
            return
        t = " ".join(data.split())
        if t:
            self.parts.append(t)


def page_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html)
    return " ".join(p.parts)


def research(story: dict) -> dict:
    """Fetch the official article, refuse the job if facts do not check out."""
    article = story["article_url"]
    video = story["video_url"]
    still = story["still_url"]
    if not host_ok(article):
        raise SystemExit(f"Article host not allowlisted: {article}")
    if not host_ok(video):
        raise SystemExit(f"Video host not allowlisted: {video}")
    if not still.startswith("https://"):
        raise SystemExit(f"Still must be public https: {still}")
    if "@" in still:
        raise SystemExit(f"Late encodes @ as %40 — do not use jsDelivr @ URLs: {still}")

    code, html = http_get(article)
    if code != 200 or not html:
        raise SystemExit(f"Official article did not load ({code}): {article}")
    text = page_text(html)
    missing = [w for w in story["must_contain"] if w.lower() not in text.lower()]
    if missing:
        raise SystemExit(f"Article missing expected facts {missing}: {article}")

    # Soft checks — warn, do not invent replacements.
    for needle in (story["facts"]["sunday_score"], "Hovland", "16"):
        if needle.lower() not in text.lower():
            print(f"WARN: article text did not contain {needle!r}", file=sys.stderr)

    if not http_head_ok(video):
        raise SystemExit(f"Official video URL did not load: {video}")
    if not http_head_ok(still):
        raise SystemExit(f"Original still URL did not load: {still}")

    out = dict(story)
    out["researched_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    out["article_status"] = code
    out["article_ok"] = True
    out["video_ok"] = True
    out["still_ok"] = True
    return out


def write_copy(story: dict) -> dict:
    """Golfer-to-golfer. No App Store. No EagleEye pitch."""
    x = (
        "Three back at East Lake. Sunday 66. Second FedEx Cup. "
        "Scottie didn't get hot. He got even.\n\n"
        f"{story['video_url']}"
    )
    ig = (
        "Three back at East Lake. Sunday 66. Second FedEx Cup. "
        "Scottie didn't get hot. He got even."
    )
    reddit = (
        "Three back at East Lake. Sunday 66. Second FedEx Cup. "
        "Scottie didn't get hot. He got even.\n\n"
        f"Official round: {story['video_url']}"
    )
    ig_comment = (
        f"Watch the official round: {story['video_url']}\n\n"
        f"PGA TOUR recap: {story['article_url']}"
    )
    n = twitter_len(x)
    if n > 280:
        raise SystemExit(f"X copy is {n} chars (limit 280)")
    banned = ("apps.apple.com", "eagleeye", "unlock", "subscription")
    blob = f"{x}\n{ig}\n{reddit}".lower()
    for b in banned:
        if b in blob:
            raise SystemExit(f"Golf-world copy must not contain {b!r}")
    return {
        "twitter": x,
        "instagram": ig,
        "reddit": reddit,
        "instagram_first_comment": ig_comment,
        "title": "Three back. Sunday 66. Second FedEx Cup.",
        "twitter_chars": n,
    }


def empty_row(headers: list[str]) -> dict[str, str]:
    return {h: "" for h in headers}


def build_csv_row(headers: list[str], story: dict, copy: dict, when: str, cfg: dict) -> dict[str, str]:
    row = empty_row(headers)
    still = story["still_url"]
    row.update(
        {
            "post_content": copy["reddit"],
            "platforms": "twitter,instagram,reddit",
            "profiles": "default",
            "schedule_time": when,
            "tz": cfg.get("timezone", "America/New_York"),
            "media_urls": still,
            "is_draft": "false",
            "publish_now": "false",
            "use_queue": "false",
            "title": copy["title"],
            "tags": "golf",
            "hashtags": "#golf",
            "visibility": "public",
            "crossposting_enabled": "true",
            "instagram_content_type": "post",
            "instagram_first_comment": copy["instagram_first_comment"],
            "instagram_is_ai_generated": "true",
            "custom_content_twitter": copy["twitter"],
            "custom_content_instagram": copy["instagram"],
            "custom_media_twitter": still,
            "custom_media_instagram": still,
            "reddit_subreddit": cfg.get("reddit_subreddit", "u_eagleeyegolfapp"),
            "reddit_nsfw": "false",
            "reddit_spoiler": "false",
        }
    )
    unknown = set(row) - set(headers)
    if unknown:
        raise SystemExit(f"CSV fields not in header: {unknown}")
    return {h: row.get(h, "") for h in headers}


def write_csv(path: Path, headers: list[str], row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerow(row)


def parse_when(s: str | None) -> str:
    now = datetime.now(TZ)
    if s:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    else:
        dt = now.replace(hour=18, minute=20, second=0, microsecond=0)
    if dt <= now + timedelta(minutes=2):
        dt = dt + timedelta(days=1)
        # keep 18:20 clock if the requested time already passed
        if not s:
            dt = dt.replace(hour=18, minute=20, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%d %H:%M")


def late_payload(story: dict, copy: dict, when: str, cfg: dict) -> dict:
    mapping = {
        "twitter": os.environ.get("LATE_TWITTER_ACCOUNT_ID", ""),
        "instagram": os.environ.get("LATE_INSTAGRAM_ACCOUNT_ID", ""),
        "reddit": os.environ.get("LATE_REDDIT_ACCOUNT_ID", ""),
    }
    platforms = []
    for name in cfg.get("platforms_stills", ["twitter", "instagram", "reddit"]):
        acc = mapping.get(name, "")
        if not acc:
            continue
        item: dict = {
            "platform": name,
            "accountId": acc,
            "customContent": copy.get(name, copy["reddit"]),
        }
        if name == "instagram":
            item["platformSpecificData"] = {
                "contentType": "post",
                "firstComment": copy["instagram_first_comment"],
            }
        if name == "reddit":
            item["platformSpecificData"] = {
                "subreddit": cfg.get("reddit_subreddit", "u_eagleeyegolfapp")
            }
        platforms.append(item)
    if not platforms:
        raise SystemExit("No LATE_*_ACCOUNT_ID in .env")
    payload = {
        "content": copy["reddit"],
        "title": copy["title"],
        "timezone": cfg.get("timezone", "America/New_York"),
        "scheduledFor": when.replace(" ", "T"),
        "publishNow": False,
        "isDraft": False,
        "mediaItems": [{"url": story["still_url"], "type": "image"}],
        "platforms": platforms,
    }
    if os.environ.get("LATE_PROFILE_ID"):
        payload["profileId"] = os.environ["LATE_PROFILE_ID"]
    return payload


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
        "source_url",
        "video_url",
        "late_id",
        "status",
    ]
    new = not log.exists()
    # Upgrade header if an older log exists without the new columns.
    if not new:
        with log.open(newline="", encoding="utf-8") as f:
            existing = next(csv.reader(f), [])
        if existing != fields:
            prev = list(csv.DictReader(log.open(newline="", encoding="utf-8")))
            with log.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for r in prev:
                    w.writerow({k: r.get(k, "") for k in fields})
            new = False
    with log.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def run(when: str, dry: bool, live: bool) -> None:
    cfg = load_config()
    story = research(CANONICAL)
    copy = write_copy(story)
    on_github = bool(os.environ.get("GITHUB_ACTIONS"))
    job_path = HERE / "state" / "workflow1_job.json"
    csv_path = HERE / "out" / "workflow1_one_post.csv"
    desktop_csv = DESKTOP / "eagleeye_workflow1_one_post.csv"
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job = {
        "kind": "golf-world",
        "when": when,
        "tz": cfg.get("timezone", "America/New_York"),
        "story": story,
        "copy": copy,
        "legal": {
            "do_not_download_broadcast": True,
            "x": "text + official YouTube URL (link card), original still attached",
            "instagram": "original still + first comment = official watch/read links",
            "reddit": "profile u_eagleeyegolfapp, official URL in body",
        },
        "csv": str(csv_path),
    }
    job_path.write_text(json.dumps(job, indent=2) + "\n")
    if not on_github and SAMPLE_CSV.exists():
        headers = csv_headers()
        row = build_csv_row(headers, story, copy, when, cfg)
        write_csv(csv_path, headers, row)
        try:
            write_csv(desktop_csv, headers, row)
        except OSError:
            pass

    print("KIND        golf-world (Workflow 1)")
    print("WHEN        ", when, cfg.get("timezone"))
    print("STORY       ", story["headline"])
    print("ARTICLE     ", story["article_url"])
    print("VIDEO       ", story["video_url"], f"({story['video_channel']})")
    print("STILL       ", story["still_url"])
    print("X CHARS     ", copy["twitter_chars"])
    print("X COPY      ", copy["twitter"].replace("\n", " / "))
    if not on_github:
        print("CSV         ", csv_path)
        print("DESKTOP     ", desktop_csv)
    print("JOB         ", job_path)

    late_id, status = "", "csv-ready"
    if live and not dry:
        if not os.environ.get("LATE_API_KEY", "").strip():
            print("LATE        skipped — no LATE_API_KEY in automation/.env")
            print("             Paste the key, save the file, then rerun --live.")
            status = "csv-ready-no-api-key"
        else:
            from late_client import create_post, persist_ids, resolve_accounts

            found = resolve_accounts()
            persist_ids(found)
            payload = late_payload(story, copy, when, cfg)
            idem = f"eagleeye-{story['id']}-{when.replace(' ', 'T')}"
            res = create_post(payload, idempotency_key=idem)
            post = res.get("post") or res.get("existingPost") or res
            late_id = str(post.get("_id") or post.get("id") or "")
            status = str(post.get("status") or "submitted")
            print("LATE        ", late_id, status)
            job["late_id"] = late_id
            job["late_status"] = status
            job_path.write_text(json.dumps(job, indent=2) + "\n")
    else:
        print("LATE        dry-run (pass --live after LATE_API_KEY is set)")

    append_log(
        {
            "ts": datetime.now(TZ).isoformat(timespec="seconds"),
            "kind": "golf-world",
            "bank_id": story["id"],
            "schedule_time": when,
            "copy": copy["twitter"],
            "media_url": story["still_url"],
            "source_url": story["article_url"],
            "video_url": story["video_url"],
            "late_id": late_id,
            "status": status,
        }
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--when", help='Local time "YYYY-MM-DD HH:MM"')
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--live", action="store_true", help="POST to Late if key exists")
    args = ap.parse_args()
    when = parse_when(args.when)
    dry = args.dry_run or not args.live
    run(when, dry=dry, live=args.live)


if __name__ == "__main__":
    main()
