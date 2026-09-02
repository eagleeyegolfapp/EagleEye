#!/usr/bin/env python3
"""Title filters, URL keys, and scoring for news/community picks."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

JUNK = re.compile(
    r"\b("
    r"tennis|fortnite|warzone|xbox|playstation|nintendo|"
    r"nba|nfl|nhl|mlb|hockey|basketball|soccer|fifa|"
    r"ufc|\bmma\b|boxing|formula 1|\bf1\b|nascar|"
    r"minecraft|roblox|\bgta\b|call of duty|valorant|"
    r"wwe|wrestling|poker tournament|us open tennis"
    r")\b",
    re.I,
)
LIVE_JUNK = re.compile(
    r"\b(live stream|livestream|subathon|24/7 live|watch along live)\b",
    re.I,
)
LONGFORM = re.compile(
    r"\b(full (?:final )?round|full replay|extended highlights|entire round|round \d replay)\b",
    re.I,
)
YEAR = re.compile(r"\b(20[12]\d)\b")
HOOKY = (
    "hole in one",
    "albatross",
    "walk-off",
    "playoff",
    " wins",
    "winning",
    "insane",
    "unbelievable",
    "meltdown",
    "choke",
    "record",
    " ace",
    "roast",
    " vs ",
    "versus",
    "highlights",
    "final round",
    "shot of",
    "banned",
    "slow play",
    "rules official",
    "eagle",
    "albatross",
    "chip-in",
    "hole-out",
    "sunday",
)


def youtube_id_from_url(url: str) -> str:
    m = re.search(r"(?:youtu\.be/|v=|/shorts/)([\w-]{6,})", url or "")
    return m.group(1) if m else ""


def norm_url(url: str) -> str:
    u = (url or "").strip()
    if not u.startswith("http"):
        return ""
    p = urlparse(u)
    host = (p.netloc or "").lower().removeprefix("www.")
    path = (p.path or "").rstrip("/")
    if "youtu" in host:
        vid = youtube_id_from_url(u)
        if vid:
            return f"youtube:{vid}"
    if host in {"x.com", "twitter.com"}:
        m = re.search(r"/status/(\d+)", path)
        if m:
            return f"x:{m.group(1)}"
    return urlunparse(("", host, path, "", "", "")).lower()


def fingerprint(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())[:80]


def keep_title(title: str) -> bool:
    t = (title or "").strip()
    if len(t) < 12:
        return False
    if t.lower() in {"private video", "deleted video", "this clip"}:
        return False
    if JUNK.search(t):
        return False
    if LIVE_JUNK.search(t):
        return False
    if LONGFORM.search(t):
        return False
    years = [int(y) for y in YEAR.findall(t)]
    now_y = datetime.now().year
    if years and now_y not in years and max(years) < now_y:
        return False
    return True


def story_keys(obj: dict) -> list[str]:
    keys: list[str] = []
    vid = (obj.get("video_id") or "") or youtube_id_from_url(
        obj.get("video_url") or obj.get("article_url") or obj.get("url") or ""
    )
    if vid:
        keys.append(str(vid))
        keys.append("yt-" + str(vid))
        keys.append("x-" + str(vid) if str(vid).isdigit() else "")
    for u in (obj.get("video_url"), obj.get("article_url"), obj.get("url")):
        n = norm_url(u or "")
        if n:
            keys.append(n)
    fp = fingerprint(obj.get("title") or obj.get("headline") or obj.get("video_title") or "")
    if len(fp) >= 16:
        keys.append("fp:" + fp)
    sid = obj.get("id") or ""
    if sid:
        keys.append(str(sid))
    return [k for k in keys if k]


def recency_points(published: str) -> float:
    if not published:
        return 8.0
    raw = published.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return 8.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0
    if hours < 0:
        return 22.0
    if hours < 3:
        return 28.0
    if hours < 24:
        return 42.0
    if hours < 48:
        return 30.0
    if hours < 72:
        return 16.0
    if hours < 24 * 8:
        return 6.0
    return -60.0


def score_candidate(
    *,
    title: str,
    published: str = "",
    weight: int = 3,
    event_boost: int = 0,
    is_short: bool = False,
    creator_repeat: bool = False,
    has_embed: bool = True,
    lane: str = "community",
) -> float:
    if not keep_title(title):
        return -999.0
    rec = recency_points(published)
    if rec < 0 and lane == "community":
        return rec
    hook = 10.0 if any(h in (title or "").lower() for h in HOOKY) else 0.0
    short_b = 14.0 if is_short else 0.0
    embed_b = 8.0 if has_embed else 0.0
    repeat = -32.0 if creator_repeat else 0.0
    base = float(max(1, int(weight or 3))) * 3.0
    event = float(event_boost)
    if event:
        event += 24.0  # live-event stories beat random official YouTube
    return base + rec + hook + short_b + embed_b + event + repeat
