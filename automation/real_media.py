#!/usr/bin/env python3
"""Official still for THIS story: YouTube frame, Vimeo thumb, or article og:image.

Never AI. Never a quote card. Never someone else's ripped video file.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image
from media import download
from story_quality import youtube_id_from_url

IG_W, IG_H = 1080, 1350
MIN_BYTES = 8000
MIN_W, MIN_H = 480, 270


def _yt_candidates(video_id: str) -> list[str]:
    return [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    ]


def _usable(blob: bytes) -> bool:
    if not blob or len(blob) < MIN_BYTES:
        return False
    try:
        im = Image.open(io.BytesIO(blob))
        im.load()
    except Exception:
        return False
    return im.width >= MIN_W and im.height >= MIN_H


def fetch_image(url: str) -> bytes | None:
    if not url or not str(url).startswith("http"):
        return None
    try:
        blob = download(url)
    except Exception as e:  # noqa: BLE001
        print(f"  still   fail {url[:70]}: {e}")
        return None
    if not _usable(blob):
        return None
    return blob


def og_image_from_html(html: str) -> str:
    if not html:
        return ""
    for pat in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ):
        m = re.search(pat, html, re.I)
        if m:
            url = m.group(1).strip()
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("http"):
                return url
    return ""


def fit_ig_portrait(blob: bytes) -> bytes:
    """Letterbox the official image onto 4:5. Does not invent pixels of a golfer."""
    im = Image.open(io.BytesIO(blob)).convert("RGB")
    canvas = Image.new("RGB", (IG_W, IG_H), (7, 8, 10))
    ratio = min(IG_W / im.width, IG_H / im.height)
    nw, nh = max(1, int(im.width * ratio)), max(1, int(im.height * ratio))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas.paste(im, ((IG_W - nw) // 2, (IG_H - nh) // 2))
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue()


def official_still(story: dict) -> dict | None:
    """Return {url, bytes, kind} for the still that belongs to this clip/article."""
    tried: list[str] = []
    yid = youtube_id_from_url(story.get("video_url") or "") or youtube_id_from_url(
        story.get("article_url") or ""
    ) or (
        story.get("video_id")
        if story.get("video_id") and not str(story.get("video_id")).isdigit()
        else ""
    )
    if yid and not str(yid).isdigit():
        tried.extend(_yt_candidates(yid))
    for key in ("thumb", "thumbnail", "og_image", "still_url"):
        u = (story.get(key) or "").strip()
        if u and u not in tried:
            tried.append(u)

    blob = None
    src = ""
    for url in tried:
        blob = fetch_image(url)
        if blob:
            src = url
            kind = "youtube-thumb" if "ytimg.com" in url or "youtube" in url else "official-thumb"
            print(f"  still   {kind} {url[:70]}")
            return {"url": url, "bytes": blob, "kind": kind}

    page = story.get("article_url") or story.get("video_url") or ""
    if page.startswith("http") and "youtu" not in page and "vimeo.com" not in page:
        from research import http_get

        code, html = http_get(page)
        og = og_image_from_html(html) if code == 200 else ""
        if og:
            blob = fetch_image(og)
            if blob:
                print(f"  still   article og:image {og[:70]}")
                return {"url": og, "bytes": blob, "kind": "og-image"}

    print("  still   no official image for this story")
    return None


def save_preview(blob: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
