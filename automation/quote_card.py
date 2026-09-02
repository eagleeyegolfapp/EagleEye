#!/usr/bin/env python3
"""Original 4:5 quote card for Instagram. The take IS the image."""
from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
BG = (7, 8, 10)
GOLD = (201, 162, 39)
INK = (244, 239, 228)
MUTED = (142, 134, 116)
LINE = (42, 39, 28)

FONTS = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/NewYork.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
]
FONTS_REG = [
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:8]


def take_from_copy(copy: dict, story: dict) -> str:
    raw = (copy.get("instagram") or copy.get("twitter") or story.get("headline") or "").strip()
    raw = re.sub(r"https?://\S+", "", raw)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("@")]
    text = " ".join(lines[:3]) if lines else (story.get("headline") or "Golf being golf.")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 180:
        text = text[:177].rstrip() + "…"
    return text or "Golf being golf."


def render_quote_card(copy: dict, story: dict) -> bytes:
    take = take_from_copy(copy, story)
    kicker = (story.get("creator") or story.get("video_channel") or "GOLF").strip().upper()
    if len(kicker) > 28:
        kicker = kicker[:28]
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    # Gold hairline frame
    m = 48
    draw.rectangle([m, m, W - m, H - m], outline=GOLD, width=2)
    draw.rectangle([m + 8, m + 8, W - m - 8, H - m - 8], outline=LINE, width=1)

    kfont = _font(FONTS_REG, 28)
    tfont = _font(FONTS, 64)
    ffont = _font(FONTS_REG, 26)

    draw.text((W // 2, 160), kicker, font=kfont, fill=GOLD, anchor="mt")
    draw.line([(W // 2 - 40, 200), (W // 2 + 40, 200)], fill=GOLD, width=2)

    body_w = W - 180
    # Shrink type until it fits the middle band.
    size = 64
    lines: list[str] = []
    font = tfont
    while size >= 36:
        font = _font(FONTS, size)
        lines = _wrap(draw, take, font, body_w)
        line_h = int(size * 1.22)
        total = line_h * len(lines)
        if total <= 720 and all(draw.textlength(ln, font=font) <= body_w for ln in lines):
            break
        size -= 4
    line_h = int(size * 1.22)
    y = (H - line_h * len(lines)) // 2 - 20
    for ln in lines:
        draw.text((W // 2, y), ln, font=font, fill=INK, anchor="mt")
        y += line_h

    draw.line([(W // 2 - 80, H - 210), (W // 2 + 80, H - 210)], fill=LINE, width=1)
    draw.text((W // 2, H - 170), "Watch the clip — link in comments", font=ffont, fill=MUTED, anchor="mt")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()
