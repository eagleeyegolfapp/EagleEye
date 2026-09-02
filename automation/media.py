#!/usr/bin/env python3
"""Always attach an original still. Official videos are linked, never ripped."""
from __future__ import annotations

import json
import os
import ssl
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CTX = ssl.create_default_context()
XAI = "https://api.x.ai/v1"
FALLBACK = (
    "https://raw.githubusercontent.com/TheSgambini/eagleeyelabsllc"
    "/main/_late-media/test-golf-world-first-tee.jpg"
)

GOLF_STILL_RULES = (
    "Photoreal golf photograph, 4:5, no famous players, no readable faces, "
    "no fake leaderboards, no competitor app UI, no logos. "
    "Crushed blacks, warm late-day light. Public-course honesty, not Augusta fantasy."
)


def _http_json(url: str, body: dict, key: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90, context=CTX) as resp:
        return json.loads(resp.read().decode())


def generate_still(prompt: str, slug: str) -> str | None:
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        return None
    body = {
        "model": os.environ.get("XAI_IMAGE_MODEL", "grok-imagine-image"),
        "prompt": f"{prompt}\n{GOLF_STILL_RULES}",
        "aspect_ratio": "3:4",
        "n": 1,
        "storage_options": {"filename": f"{slug}.jpg", "public_url": True},
    }
    try:
        data = _http_json(f"{XAI}/images/generations", body, key)
    except Exception as e:  # noqa: BLE001
        print(f"  imagine failed: {e}")
        return None
    item = (data.get("data") or [None])[0] or {}
    url = (
        item.get("public_url")
        or (item.get("file_output") or {}).get("public_url")
        or item.get("url")
    )
    return url or None


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "EagleEyeGolf-media/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
        return resp.read()


def _http_get_json(url: str, key: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30, context=CTX) as resp:
        return json.loads(resp.read().decode())


def generate_short(prompt: str, image_url: str | None = None, seconds: int = 6) -> str | None:
    """Original 9:16 short. We never upload someone else's file."""
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        return None
    body: dict = {
        "model": os.environ.get("XAI_VIDEO_MODEL", "grok-imagine-video"),
        "prompt": (
            f"{prompt}\nPhotoreal golf, no famous faces, no logos, no TV graphics, "
            "no readable scoreboards. Vertical 9:16, phone-in-hand energy."
        ),
        "duration": seconds,
        "aspect_ratio": "9:16",
        "resolution": "480p",
    }
    if image_url:
        body["image"] = {"url": image_url}
    try:
        start = _http_json(f"{XAI}/videos/generations", body, key)
    except Exception as e:  # noqa: BLE001
        print(f"  short   start failed: {e}")
        return None
    rid = start.get("request_id") or start.get("id")
    if not rid:
        url = (start.get("video") or {}).get("url") or start.get("url")
        return url if url and str(url).startswith("https://") else None
    import time

    for _ in range(24):
        time.sleep(5)
        try:
            data = _http_get_json(f"{XAI}/videos/{rid}", key)
        except Exception as e:  # noqa: BLE001
            print(f"  short   poll failed: {e}")
            return None
        status = (data.get("status") or "").lower()
        if status in {"done", "succeeded", "complete", "completed"}:
            url = (data.get("video") or {}).get("url") or data.get("url")
            if url and str(url).startswith("https://"):
                print("  short   generated")
                return url
            return None
        if status in {"failed", "expired", "error"}:
            print(f"  short   {status}")
            return None
    print("  short   timed out")
    return None


def still_for(story: dict, cfg: dict) -> str:
    """Return a public https JPEG URL. Never empty."""
    fallback = cfg.get("fallback_still") or FALLBACK
    if not cfg.get("media", {}).get("generate_still", True):
        return story.get("still_url") or fallback
    prompt = story.get("still_prompt") or (
        "Dawn on a public first tee. One ball on a wooden tee, frost in the "
        "shadow of the ball washer, empty fairway stretching out."
    )
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in story.get("id", "still"))[:60]
    url = generate_still(prompt, slug)
    if url and url.startswith("https://"):
        print("  still  generated")
        return url
    if story.get("still_url"):
        print("  still  story url")
        return story["still_url"]
    print("  still  fallback")
    return fallback
