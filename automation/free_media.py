#!/usr/bin/env python3
"""Hand-picked cinematic golf B-roll. Pexels license. Never random Commons junk.

Every URL was opened and the first frame inspected. Keep only drone / fairway /
green / bunker / water-hazard golf. Reject gym, code, ocean, city, trees-only.
"""
from __future__ import annotations

import random
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_BYTES = 80_000_000

# weight: higher = more likely. 4K and the widest cinematic drones win.
CATALOG = [
    {
        "id": "3214020",
        "title": "4K aerial over a mountain golf course",
        "url": "https://videos.pexels.com/video-files/3214020/3214020-uhd_3840_2160_25fps.mp4",
        "fallbacks": [
            "https://videos.pexels.com/video-files/3214020/3214020-hd_1920_1080_25fps.mp4",
        ],
        "license": "Pexels",
        "credit": "Pexels",
        "weight": 3,
    },
    {
        "id": "17239356",
        "title": "High drone over a full golf course, ponds and bunkers",
        "url": "https://videos.pexels.com/video-files/17239356/17239356-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "Pexels",
        "weight": 3,
    },
    {
        "id": "15508702",
        "title": "Seaside golf course, bunkers and lagoons",
        "url": "https://videos.pexels.com/video-files/15508702/15508702-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "HUAHIN PILOT LAND / Pexels",
        "weight": 3,
    },
    {
        "id": "854337",
        "title": "Palm-lined green, bunkers, desert light",
        "url": "https://videos.pexels.com/video-files/854337/854337-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "Pixabay / Pexels",
        "weight": 3,
    },
    {
        "id": "18138326",
        "title": "Drone over a striped fairway and pond",
        "url": "https://videos.pexels.com/video-files/18138326/18138326-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "Jaxon Matthew Willis / Pexels",
        "weight": 2,
    },
    {
        "id": "18138335",
        "title": "High aerial of mowed fairways and a creek",
        "url": "https://videos.pexels.com/video-files/18138335/18138335-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "Jaxon Matthew Willis / Pexels",
        "weight": 2,
    },
    {
        "id": "18138329",
        "title": "Wide aerial: bunkers, pond, tree-lined holes",
        "url": "https://videos.pexels.com/video-files/18138329/18138329-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "Jaxon Matthew Willis / Pexels",
        "weight": 2,
    },
    {
        "id": "18138331",
        "title": "Overhead of a hole wrapping a creek",
        "url": "https://videos.pexels.com/video-files/18138331/18138331-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "Jaxon Matthew Willis / Pexels",
        "weight": 1,
    },
    {
        "id": "18451070",
        "title": "Top-down green, bunkers, water",
        "url": "https://videos.pexels.com/video-files/18451070/18451070-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "Pexels",
        "weight": 2,
    },
    {
        "id": "18451072",
        "title": "Overhead greens along the water",
        "url": "https://videos.pexels.com/video-files/18451072/18451072-hd_1920_1080_30fps.mp4",
        "license": "Pexels",
        "credit": "Pexels",
        "weight": 2,
    },
]


def local_broll() -> list[Path]:
    folder = HERE / "broll"
    if not folder.is_dir():
        return []
    return [p for p in list(folder.glob("*.mp4")) + list(folder.glob("*.mov")) if p.stat().st_size > 200_000]


def clip_urls(clip: dict) -> list[str]:
    """HD first (reliable encode), 4K after. Output is 1080x1920 either way."""
    urls = [clip["url"]] + list(clip.get("fallbacks") or [])
    seen: set[str] = set()
    hd: list[str] = []
    uhd: list[str] = []
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        if "uhd_" in u or "3840" in u:
            uhd.append(u)
        else:
            hd.append(u)
    return hd + uhd


def pick_free_clip(used: set[str] | None = None) -> dict | None:
    used = used or set()
    bag = [c for c in CATALOG if c["url"] not in used and c["id"] not in used]
    if not bag:
        bag = list(CATALOG)
    weights = [max(1, int(c.get("weight") or 1)) for c in bag]
    return dict(random.choices(bag, weights=weights, k=1)[0])


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "video/mp4,video/*,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(MAX_BYTES + 1)


def download_free(url: str) -> bytes | None:
    try:
        blob = _get(url, timeout=90)
    except Exception as e:  # noqa: BLE001
        print("  broll   download failed:", e)
        return None
    if not blob or len(blob) < 400_000:
        print("  broll   file too small", 0 if not blob else len(blob))
        return None
    if len(blob) > MAX_BYTES:
        print("  broll   file too large, skip")
        return None
    return blob


def broll_story(clip: dict | None = None) -> dict:
    clip = clip or pick_free_clip() or CATALOG[0]
    return {
        "id": f"broll-{clip['id']}",
        "lane": "community",
        "headline": "The game",
        "creator": "GOLF",
        "video_channel": "GOLF",
        "video_url": clip["url"],
        "article_url": "",
        "excerpt": clip.get("title") or "Cinematic golf course aerial",
        "broll": True,
        "license": clip.get("license") or "Pexels",
        "credit": clip.get("credit") or "",
        "clip": clip,
    }
