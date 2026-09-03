#!/usr/bin/env python3
"""Free-use golf clips (Wikimedia Commons). Never a Tour broadcast file."""
from __future__ import annotations

import json
import random
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "EagleEyeGolfApp/1.0 (golf app; eagleeyegolfapp@gmail.com)"
MAX_BYTES = 28_000_000

# Known-good CC clips so a dead search still has something real to post.
SEED = [
    "https://upload.wikimedia.org/wikipedia/commons/2/2e/Golf_swing_practice_-_Kanagawa_-_slow_motion_-_2023_June_13.webm",
    "https://upload.wikimedia.org/wikipedia/commons/0/0e/Manpracticinggolfswing-slowmotion-2021-3-24.webm",
    "https://upload.wikimedia.org/wikipedia/commons/9/9e/Suvichaya_Vinijchaitham_Golf_Swing_Slow_Mo_2026.webm",
]


def _get(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def search_commons(query: str = "golf swing", limit: int = 8) -> list[dict]:
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{query} filetype:video",
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
        }
    )
    try:
        data = json.loads(_get("https://commons.wikimedia.org/w/api.php?" + q, timeout=20).decode())
    except Exception as e:  # noqa: BLE001
        print("  free    commons search failed:", e)
        return []
    out = []
    for p in (data.get("query") or {}).get("pages", {}).values():
        info = (p.get("imageinfo") or [{}])[0]
        url = info.get("url") or ""
        size = int(info.get("size") or 0)
        mime = (info.get("mime") or "").lower()
        if not url or size < 400_000 or size > MAX_BYTES:
            continue
        if "video" not in mime and "ogg" not in mime:
            continue
        license_ = ""
        meta = info.get("extmetadata") or {}
        if isinstance(meta, dict):
            license_ = (meta.get("LicenseShortName") or {}).get("value") or ""
        out.append(
            {
                "url": url,
                "title": p.get("title") or "golf clip",
                "license": license_ or "CC",
                "bytes": size,
            }
        )
    return out


def pick_free_clip(used: set[str] | None = None) -> dict | None:
    used = used or set()
    hits = search_commons("golf swing") + search_commons("golf course")
    random.shuffle(hits)
    for h in hits + [{"url": u, "title": "golf swing", "license": "CC"} for u in SEED]:
        if h["url"] in used:
            continue
        return h
    return None


def download_free(url: str) -> bytes | None:
    try:
        blob = _get(url, timeout=90)
    except Exception as e:  # noqa: BLE001
        print("  free    download failed:", e)
        return None
    if not blob or len(blob) < 80_000:
        return None
    return blob
