#!/usr/bin/env python3
"""Original 9:16 take card. The take IS the post — no 'link in comments'."""
from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
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


def split_take(copy: dict, story: dict) -> tuple[str, str]:
    """Hero take + optional question. Strips URLs and @handles."""
    raw = (copy.get("instagram") or copy.get("twitter") or story.get("headline") or "").strip()
    raw = re.sub(r"https?://\S+", "", raw)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("@")]
    question = ""
    body: list[str] = []
    for ln in lines:
        if "?" in ln and not question:
            question = ln
        else:
            body.append(ln)
    take = " ".join(body) if body else (question or story.get("headline") or "Golf being golf.")
    take = re.sub(r"\s+", " ", take).strip()
    if question:
        question = re.sub(r"\s+", " ", question).strip()
        if question.rstrip("?") == take.rstrip("?"):
            # The whole caption was a question — keep it as the hero.
            take, question = question, ""
    if len(take) > 170:
        take = take[:167].rstrip() + "…"
    if len(question) > 96:
        question = question[:93].rstrip() + "…"
    return take or "Golf being golf.", question


def take_from_copy(copy: dict, story: dict) -> str:
    take, question = split_take(copy, story)
    return f"{take} {question}".strip()


def render_quote_card(copy: dict, story: dict, tease: bool = False) -> bytes:
    take, question = split_take(copy, story)
    kicker = (story.get("creator") or story.get("video_channel") or "GOLF").strip().upper()
    if len(kicker) > 28:
        kicker = kicker[:28]
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    m = 56
    draw.rectangle([m, m, W - m, H - m], outline=GOLD, width=2)
    draw.rectangle([m + 8, m + 8, W - m - 8, H - m - 8], outline=LINE, width=1)

    kfont = _font(FONTS_REG, 30)
    qfont = _font(FONTS_REG, 32)
    draw.text((W // 2, 220), kicker, font=kfont, fill=GOLD, anchor="mt")
    draw.line([(W // 2 - 48, 268), (W // 2 + 48, 268)], fill=GOLD, width=2)

    body_w = W - 200
    if tease:
        # Beat 1: kicker only. The take slams in on the next frame.
        pass
    else:
        size = 72
        lines: list[str] = []
        font = _font(FONTS, size)
        while size >= 38:
            font = _font(FONTS, size)
            lines = _wrap(draw, take, font, body_w)
            line_h = int(size * 1.2)
            total = line_h * len(lines)
            if total <= 820 and all(draw.textlength(ln, font=font) <= body_w for ln in lines):
                break
            size -= 4
        line_h = int(size * 1.2)
        y = (H - line_h * len(lines)) // 2 - (40 if question else 0)
        for ln in lines:
            draw.text((W // 2, y), ln, font=font, fill=INK, anchor="mt")
            y += line_h
        if question:
            q_lines = _wrap(draw, question, qfont, body_w)
            qy = H - 280 - int(38 * (len(q_lines) - 1))
            draw.line([(W // 2 - 80, qy - 36), (W // 2 + 80, qy - 36)], fill=LINE, width=1)
            for qln in q_lines[:3]:
                draw.text((W // 2, qy), qln, font=qfont, fill=GOLD, anchor="mt")
                qy += 42

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()
