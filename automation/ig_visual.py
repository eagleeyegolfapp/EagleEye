#!/usr/bin/env python3
"""Instagram visuals: real frame of THIS clip + original type.

Not a naked YouTube thumb. Not a black quote card. Not ripped video.
The overlay is a 4–8 word hook. The caption carries the rest of the take.
"""
from __future__ import annotations

import hashlib
import io
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from quote_card import split_take

FEED_W, FEED_H = 1080, 1350
STORY_W, STORY_H = 1080, 1920
GOLD = (201, 162, 39)
INK = (244, 239, 228)
MUTED = (196, 186, 160)
DARK = (7, 8, 10)

# Grid on IG is the center square of 4:5 → y 135..1215. Type lives there.
GRID_TOP, GRID_BOT = 135, 1215

STYLES = ("broadcast", "carousel", "clean", "editorial", "cover", "split", "scorebug")

_DISPLAY = [
    ("/System/Library/Fonts/Supplemental/Didot.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Bodoni 72.ttc", 1),
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]
_BODY = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/NewYork.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]
_UI = [
    "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
    "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf",
    ("/System/Library/Fonts/Supplemental/Avenir Next Condensed.ttc", 4),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
_UI_REG = [
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    ("/System/Library/Fonts/HelveticaNeue.ttc", 0),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _ff(cands: list, size: int) -> ImageFont.ImageFont:
    for item in cands:
        path, idx = item if isinstance(item, tuple) else (item, 0)
        if not Path(path).exists():
            continue
        try:
            return ImageFont.truetype(path, size, index=idx)
        except Exception:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, limit: int = 6) -> list[str]:
    words = (text or "").split()
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
    return lines[:limit]


def _kicker(story: dict) -> str:
    raw = (story.get("creator") or story.get("video_channel") or "GOLF").strip()
    raw = re.sub(r"^@", "", raw)
    k = raw.upper()
    if len(k) > 24:
        k = k[:24]
    return k or "GOLF"


def _jpeg(img: Image.Image, quality: int = 93) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True, subsampling=0)
    return buf.getvalue()


def _edge_score(g: Image.Image, box: tuple[int, int, int, int]) -> float:
    c = g.crop(box)
    if c.width < 4 or c.height < 4:
        return 0.0
    e = c.resize((48, 48), Image.Resampling.BILINEAR).filter(ImageFilter.FIND_EDGES)
    data = list(e.getdata())
    return sum(data) / max(1, len(data))


def _pillar_seams(g: Image.Image) -> tuple[int, int] | None:
    """Vertical seams of a 9:16 Short packed into a 16:9 YouTube thumb."""
    w, h = g.size
    if w / max(1, h) < 1.28:
        return None
    slim = g.resize((w, 24), Image.Resampling.BILINEAR)
    px = slim.load()
    means = [sum(px[x, y] for y in range(24)) / 24.0 for x in range(w)]
    diffs = [0.0] + [abs(means[i] - means[i - 1]) for i in range(1, w)]
    sm = diffs[:]
    for i in range(2, len(diffs) - 2):
        sm[i] = sum(diffs[i - 2 : i + 3]) / 5.0
    split_l, split_r = int(w * 0.45), int(w * 0.55)
    left_zone, right_zone = sm[:split_l], sm[split_r:]
    if not left_zone or not right_zone:
        return None
    left_i = max(range(len(left_zone)), key=lambda i: left_zone[i])
    right_i = max(range(len(right_zone)), key=lambda i: right_zone[i]) + split_r
    med = sorted(sm)[len(sm) // 2]
    floor = max(7.0, med * 2.8)
    if left_zone[left_i] < floor or right_zone[right_i - split_r] < floor:
        return None
    inner = right_i - left_i
    if inner < w * 0.20 or inner > w * 0.62:
        return None
    return left_i + 2, right_i - 2


def strip_letterbox(im: Image.Image, thresh: int = 22) -> Image.Image:
    """Crop baked-in YouTube/X black bars AND Shorts pillarbox."""
    im = im.convert("RGB")
    g = im.convert("L")
    w, h = g.size
    px = g.load()

    def col_mean(x: int) -> float:
        return sum(px[x, y] for y in range(0, h, 4)) / max(1, h / 4)

    def row_mean(y: int) -> float:
        return sum(px[x, y] for x in range(0, w, 4)) / max(1, w / 4)

    left, right = 0, w - 1
    top, bot = 0, h - 1

    seams = _pillar_seams(g)
    if seams:
        left, right = seams

    while left < int(w * 0.34) and col_mean(left) < thresh:
        left += 1
    while right > int(w * 0.66) and col_mean(right) < thresh:
        right -= 1
    while top < int(h * 0.34) and row_mean(top) < thresh:
        top += 1
    while bot > int(h * 0.66) and row_mean(bot) < thresh:
        bot -= 1

    nw, nh = right - left + 1, bot - top + 1
    if nw < int(w * 0.20) or nh < int(h * 0.42):
        return im
    if nw >= w - 4 and nh >= h - 4:
        return im
    return im.crop((left, top, right + 1, bot + 1))


def is_weak_still(blob: bytes) -> bool:
    """Skip IG when the source frame will look like junk on a grid."""
    if not blob or len(blob) < 8000:
        return True
    try:
        im = strip_letterbox(Image.open(io.BytesIO(blob)).convert("RGB"))
    except Exception:
        return True
    w, h = im.size
    # Shorts packed in 16:9 maxres are ~400px wide after pillar crop.
    if w < 300 or h < 270 or (w * h) < 90000:
        return True
    extrema = im.getextrema()
    spans = [hi - lo for lo, hi in extrema]
    if max(spans) < 28:
        return True
    px = list(im.resize((64, 64)).getdata())
    avg = tuple(sum(c[i] for c in px) / len(px) for i in range(3))
    if sum(avg) < 36:
        return True
    # End-card / title-card: huge flat region + very little edge energy.
    g = im.convert("L")
    if _edge_score(g, (0, 0, w, h)) < 4.5:
        return True
    return False


def _grade(im: Image.Image) -> Image.Image:
    im = ImageEnhance.Contrast(im).enhance(1.16)
    im = ImageEnhance.Color(im).enhance(1.12)
    im = ImageEnhance.Sharpness(im).enhance(1.22)
    warm = Image.new("RGB", im.size, (26, 14, 4))
    im = Image.blend(im, warm, 0.06)
    try:
        noise = Image.effect_noise(im.size, 14).convert("L")
        grain = Image.merge("RGB", (noise, noise, noise))
        im = Image.blend(im, grain, 0.055)
    except Exception:
        pass
    return _vignette(im)


def _vignette(im: Image.Image, strength: float = 0.38) -> Image.Image:
    w, h = im.size
    sw, sh = max(16, w // 8), max(16, h // 8)
    mask = Image.new("L", (sw, sh), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-int(sw * 0.10), -int(sh * 0.08), int(sw * 1.10), int(sh * 1.08)], fill=255)
    mask = mask.resize((w, h), Image.Resampling.BILINEAR)
    mixed = Image.composite(im, Image.new("RGB", (w, h), DARK), mask)
    return Image.blend(im, mixed, strength)


def _caption_chip_in_top(im: Image.Image) -> bool:
    """YouTube/X on-video title chips sit in the upper third as saturated pills."""
    w, h = im.size
    if h <= w:
        return False
    band = im.crop((int(w * 0.10), int(h * 0.04), int(w * 0.90), int(h * 0.40)))
    small = band.resize((60, 24), Image.Resampling.BILINEAR)
    n = 0
    for r, g, b in small.getdata():
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn > 48 and mx > 90 and not (g > r + 12 and g > b + 12):
            n += 1
    return n > 70


def _auto_bias(im: Image.Image) -> str:
    if _caption_chip_in_top(im):
        return "south"
    g = im.convert("L")
    w, h = g.size
    top = _edge_score(g, (int(w * 0.18), 0, int(w * 0.82), int(h * 0.45)))
    bot = _edge_score(g, (int(w * 0.18), int(h * 0.45), int(w * 0.82), h))
    if bot > top * 1.18:
        return "south"
    if top > bot * 1.18:
        return "north"
    return "center"


def smart_crop(im: Image.Image, tw: int, th: int, bias: str = "auto") -> Image.Image:
    """Fill target ratio by cropping. Auto-bias keeps the subject, dumps title cards."""
    im = strip_letterbox(im.convert("RGB"))
    if _caption_chip_in_top(im) and im.height >= im.width:
        bias = "south"
    elif bias == "auto":
        bias = _auto_bias(im)
    src_r = im.width / max(1, im.height)
    dst_r = tw / th
    if src_r > dst_r:
        nw = int(im.height * dst_r)
        extra = im.width - nw
        if bias == "east":
            left = int(extra * 0.72)
        elif bias == "west":
            left = int(extra * 0.18)
        else:
            left = extra // 2
        im = im.crop((left, 0, left + nw, im.height))
    elif src_r < dst_r:
        nh = int(im.width / dst_r)
        extra = im.height - nh
        if bias == "north":
            top = int(extra * 0.10)
        elif bias == "south":
            top = int(extra * 0.94)
        else:
            top = int(extra * 0.32)
        im = im.crop((0, top, im.width, top + nh))
    return _grade(im.resize((tw, th), Image.Resampling.LANCZOS))


def _bias_for(story_id: str) -> str:
    h = int(hashlib.sha1(story_id.encode()).hexdigest()[:8], 16)
    return ("auto", "north", "west", "east", "auto", "south")[h % 6]


def _gradient_mask(size: tuple[int, int], frac: float, power: float = 0.72, max_a: int = 225) -> Image.Image:
    w, h = size
    start = int(h * (1.0 - frac))
    col = Image.new("L", (1, h), 0)
    pix = col.load()
    span = max(1, h - start)
    for y in range(start, h):
        t = (y - start) / span
        pix[0, y] = int(max_a * (t ** power))
    return col.resize((w, h), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(8))


def _apply_bottom_dark(photo: Image.Image, frac: float = 0.42, max_a: int = 225) -> Image.Image:
    black = Image.new("RGB", photo.size, DARK)
    return Image.composite(black, photo, _gradient_mask(photo.size, frac, max_a=max_a))


def _shadow_text(
    base: Image.Image,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    anchor: str = "lt",
    shadow: int = 3,
) -> None:
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    x, y = xy
    d.text((x + shadow, y + shadow), text, font=font, fill=(0, 0, 0, 170), anchor=anchor)
    d.text((x, y), text, font=font, fill=fill + (255,), anchor=anchor)
    base.alpha_composite(overlay)


def _tracked(
    base: Image.Image,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    tracking: int = 6,
    anchor: str = "mt",
    shadow: int = 2,
) -> None:
    dummy = ImageDraw.Draw(base)
    widths = [dummy.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * max(0, len(text) - 1)
    x, y = xy
    if anchor.startswith("m"):
        x = x - total / 2
    elif anchor.startswith("r"):
        x = x - total
    char_anchor = {
        "mt": "lt",
        "mm": "lm",
        "mb": "lb",
        "lt": "lt",
        "lm": "lm",
        "lb": "lb",
        "rt": "lt",
        "rm": "lm",
        "rb": "lb",
    }.get(anchor, "lt")
    for ch, cw in zip(text, widths):
        _shadow_text(base, (int(x), int(y)), ch, font, fill, anchor=char_anchor, shadow=shadow)
        x += cw + tracking


def _fit_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
    max_lines: int,
    start: int,
    floor: int,
    fonts: list | None = None,
) -> tuple[ImageFont.ImageFont, list[str], int]:
    fonts = fonts or _BODY
    size = start
    lines: list[str] = []
    font = _ff(fonts, size)
    while size >= floor:
        font = _ff(fonts, size)
        lines = _wrap(draw, text, font, max_w, max_lines + 1)
        if len(lines) <= max_lines and all(draw.textlength(ln, font=font) <= max_w for ln in lines):
            break
        size -= 3
    return font, lines[:max_lines], size


def _hairline(draw: ImageDraw.ImageDraw, w: int, h: int, pad: int = 28) -> None:
    draw.rectangle([pad, pad, w - pad, h - pad], outline=(201, 162, 39, 80), width=1)


def _strip_kicker(text: str, kicker: str) -> str:
    t = re.sub(r"https?://\S+", "", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    if kicker:
        t = re.sub(
            r"^" + re.escape(kicker) + r"(?:['’`]s)?\s*[:\-—,]?\s*",
            "",
            t,
            flags=re.I,
        )
    return t.strip(" -—:,.'’")


def overlay_hook(copy: dict, take: str, question: str, kicker: str = "") -> str:
    raw = (copy.get("overlay_hook") or "").strip()
    if not raw:
        raw = take or question or ""
    raw = _strip_kicker(raw, kicker)
    raw = raw.strip(" \"'")
    words = [w for w in raw.split() if w]
    if len(words) > 8:
        words = words[:8]
    hook = " ".join(words)
    if len(hook) > 52:
        hook = hook[:50].rsplit(" ", 1)[0]
    return hook.rstrip(".,;") or "Golf being golf."


def overlay_question(copy: dict, question: str) -> str:
    q = (copy.get("overlay_question") or question or "").strip()
    q = _strip_kicker(q, "")
    if len(q) > 64:
        q = q[:61].rsplit(" ", 1)[0].rstrip("?.,") + "?"
    return q


def cover_mark(hook: str) -> str:
    t = hook.strip().rstrip(".!,?")
    words = [w for w in t.split() if w]
    fill = {"the", "a", "an", "that", "this"}
    while len(words) > 4 and words[0].lower().strip("',") in fill:
        words = words[1:]
    if len(words) > 6:
        words = words[:6]
    return " ".join(words).upper() or "GOLF"


def _split_mark(mark: str) -> list[str]:
    words = mark.split()
    n = len(words)
    if n <= 2:
        return [mark]
    if n == 3:
        return [" ".join(words[:1]), " ".join(words[1:])]
    if n == 4:
        return [" ".join(words[:2]), " ".join(words[2:])]
    return [" ".join(words[:-3]), " ".join(words[-3:])]


def _pills(question: str) -> tuple[str, str]:
    q = (question or "").strip()
    parts = re.split(r"\s+\bor\b\s+", q.rstrip("?"), maxsplit=1, flags=re.I)
    if len(parts) == 2:
        a, b = parts[0].strip(), parts[1].strip()
        if 1 < len(a) <= 18 and 1 < len(b) <= 18:
            return a.upper(), b.upper()
    if re.search(r"buy|buying|sold", q, re.I):
        return "BUYING IT", "HARD PASS"
    if re.search(r"right call|fair|wrong|snub", q, re.I):
        return "RIGHT CALL", "SNUB"
    return "YES", "NO"


def _draw_pills(img: Image.Image, left: str, right: str, y: int) -> None:
    d = ImageDraw.Draw(img)
    font = _ff(_UI, 28)
    gap = 28
    pad_x, pad_y = 28, 16
    w1 = int(d.textlength(left, font=font)) + pad_x * 2
    w2 = int(d.textlength(right, font=font)) + pad_x * 2
    h = 28 + pad_y * 2
    total = w1 + w2 + gap
    x0 = (FEED_W - total) // 2
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([x0, y, x0 + w1, y + h], radius=8, outline=GOLD + (255,), width=2)
    od.rounded_rectangle(
        [x0 + w1 + gap, y, x0 + w1 + gap + w2, y + h],
        radius=8,
        fill=GOLD + (255,),
    )
    img.alpha_composite(overlay)
    _shadow_text(img, (x0 + w1 // 2, y + h // 2), left, font, GOLD, anchor="mm", shadow=1)
    _shadow_text(
        img,
        (x0 + w1 + gap + w2 // 2, y + h // 2),
        right,
        font,
        DARK,
        anchor="mm",
        shadow=0,
    )


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


def render_clean(photo: Image.Image, kicker: str) -> bytes:
    """Action-forward: the frame is the post. Tiny kicker only."""
    img = photo.convert("RGBA")
    draw = ImageDraw.Draw(img)
    _hairline(draw, FEED_W, FEED_H, 26)
    kfont = _ff(_UI, 28)
    tw = int(draw.textlength(kicker, font=kfont))
    box_w = tw + 44
    flag = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(flag)
    fd.rounded_rectangle([40, 48, 40 + box_w, 104], radius=4, fill=(7, 8, 10, 210))
    fd.rectangle([40, 48, 48, 104], fill=GOLD + (255,))
    img.alpha_composite(flag)
    _shadow_text(img, (62, 76), kicker, kfont, GOLD, anchor="lm", shadow=2)
    return _jpeg(img)


def render_broadcast(photo: Image.Image, kicker: str, hook: str, question: str, show_q: bool) -> bytes:
    """TV lower-third on the real frame. Short hook, grid-visible."""
    img = _apply_bottom_dark(photo, 0.40, 235).convert("RGBA")
    draw = ImageDraw.Draw(img)
    _hairline(draw, FEED_W, FEED_H, 26)
    kfont = _ff(_UI, 30)
    _tracked(img, (FEED_W // 2, 1008), kicker, kfont, GOLD, tracking=7, anchor="mt", shadow=2)
    draw.line([(FEED_W // 2 - 36, 1048), (FEED_W // 2 + 36, 1048)], fill=GOLD, width=2)

    body_w = FEED_W - 140
    font, lines, size = _fit_lines(draw, hook, body_w, 2 if show_q else 3, 56, 36)
    y = 1064
    for ln in lines:
        _shadow_text(img, (FEED_W // 2, y), ln, font, INK, anchor="mt", shadow=3)
        y += int(size * 1.12)
    if show_q and question:
        qfont = _ff(_UI_REG, 30)
        q_lines = _wrap(draw, question, qfont, body_w, 2)
        y += 8
        for qln in q_lines:
            _shadow_text(img, (FEED_W // 2, y), qln, qfont, GOLD, anchor="mt", shadow=2)
            y += 36
    return _jpeg(img)


def render_editorial(photo: Image.Image, kicker: str, hook: str) -> bytes:
    """Left gold spine, type stacked bottom-left. Magazine, not a poster."""
    img = _apply_bottom_dark(photo, 0.38, 230).convert("RGBA")
    draw = ImageDraw.Draw(img)
    draw.rectangle([36, 72, 46, FEED_H - 72], fill=GOLD)
    kfont = _ff(_UI, 28)
    _tracked(img, (72, 1000), kicker, kfont, GOLD, tracking=6, anchor="lt", shadow=2)
    body_w = FEED_W - 170
    font, lines, size = _fit_lines(draw, hook, body_w, 3, 52, 34)
    y = 1048
    for ln in lines:
        _shadow_text(img, (72, y), ln, font, INK, anchor="lt", shadow=3)
        y += int(size * 1.16)
    return _jpeg(img)


def render_cover(photo: Image.Image, kicker: str, mark: str, question: str) -> bytes:
    """Magazine cover. Giant 2–4 words. This is the scroll-stopper."""
    img = _apply_bottom_dark(photo, 0.48, 220).convert("RGBA")
    draw = ImageDraw.Draw(img)
    _hairline(draw, FEED_W, FEED_H, 30)
    kfont = _ff(_UI, 30)
    _tracked(img, (FEED_W // 2, 86), kicker, kfont, GOLD, tracking=8, anchor="mt", shadow=2)
    draw.line([(FEED_W // 2 - 28, 126), (FEED_W // 2 + 28, 126)], fill=GOLD, width=2)

    max_w = FEED_W - 100
    size = 108
    lines = _split_mark(mark)
    font = _ff(_DISPLAY, size)
    while size >= 52:
        font = _ff(_DISPLAY, size)
        if all(draw.textlength(ln, font=font) <= max_w for ln in lines):
            break
        size -= 4
    line_h = int(size * 1.04)
    total = line_h * len(lines)
    y = 1000 - total
    for ln in lines:
        _shadow_text(img, (FEED_W // 2, y), ln, font, INK, anchor="mt", shadow=5)
        y += line_h
    y += 8
    draw.line([(FEED_W // 2 - 48, y), (FEED_W // 2 + 48, y)], fill=GOLD, width=3)
    if question:
        qfont = _ff(_UI_REG, 32)
        q_lines = _wrap(draw, question, qfont, FEED_W - 160, 2)
        y += 22
        for qln in q_lines:
            _shadow_text(img, (FEED_W // 2, y), qln, qfont, GOLD, anchor="mt", shadow=2)
            y += 40
    return _jpeg(img)


def render_split(photo: Image.Image, kicker: str, hook: str, question: str) -> bytes:
    """Photo on top, ink panel below. Reads as a different object on the grid."""
    panel_h = 520
    photo_h = FEED_H - panel_h
    top = photo.resize((FEED_W, FEED_H), Image.Resampling.LANCZOS).crop((0, 0, FEED_W, photo_h))
    img = Image.new("RGB", (FEED_W, FEED_H), DARK)
    img.paste(top, (0, 0))
    # fade photo into the panel
    fade = Image.new("L", (FEED_W, 70), 0)
    fp = fade.load()
    for y in range(70):
        for x in range(FEED_W):
            fp[x, y] = int(255 * (y / 69))
    band = img.crop((0, photo_h - 70, FEED_W, photo_h))
    img.paste(Image.composite(Image.new("RGB", (FEED_W, 70), DARK), band, fade), (0, photo_h - 70))
    img = img.convert("RGBA")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, photo_h, FEED_W, photo_h + 4], fill=GOLD)
    kfont = _ff(_UI, 28)
    _tracked(img, (FEED_W // 2, photo_h + 36), kicker, kfont, GOLD, tracking=7, anchor="mt", shadow=1)
    draw.line(
        [(FEED_W // 2 - 32, photo_h + 76), (FEED_W // 2 + 32, photo_h + 76)],
        fill=GOLD,
        width=2,
    )
    body_w = FEED_W - 140
    font, lines, size = _fit_lines(draw, hook, body_w, 3 if not question else 2, 54, 34)
    y = photo_h + 100
    for ln in lines:
        _shadow_text(img, (FEED_W // 2, y), ln, font, INK, anchor="mt", shadow=2)
        y += int(size * 1.14)
    if question:
        qfont = _ff(_UI_REG, 30)
        y += 10
        for qln in _wrap(draw, question, qfont, body_w, 2):
            _shadow_text(img, (FEED_W // 2, y), qln, qfont, GOLD, anchor="mt", shadow=2)
            y += 36
    return _jpeg(img)


def render_scorebug(photo: Image.Image, kicker: str, hook: str) -> bytes:
    """Live-TV bug + ticker. Photo stays huge."""
    img = photo.convert("RGBA")
    kfont = _ff(_UI, 26)
    dummy = ImageDraw.Draw(img)
    tw = int(dummy.textlength(kicker, font=kfont))
    bug_w, bug_h = tw + 56, 56
    bug = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bug)
    bd.rounded_rectangle([40, 48, 40 + bug_w, 48 + bug_h], radius=6, fill=(7, 8, 10, 220))
    bd.rectangle([40, 48, 50, 48 + bug_h], fill=GOLD + (255,))
    img.alpha_composite(bug)
    _shadow_text(img, (62, 48 + bug_h // 2), kicker, kfont, GOLD, anchor="lm", shadow=1)

    bar_h = 118
    bar = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    bd.rectangle([0, FEED_H - bar_h, FEED_W, FEED_H], fill=(7, 8, 10, 230))
    bd.rectangle([0, FEED_H - bar_h, FEED_W, FEED_H - bar_h + 4], fill=GOLD + (255,))
    img.alpha_composite(bar)
    hfont, lines, size = _fit_lines(dummy, hook, FEED_W - 80, 2, 42, 30)
    y = FEED_H - bar_h + 22
    for ln in lines:
        _shadow_text(img, (FEED_W // 2, y), ln, hfont, INK, anchor="mt", shadow=2)
        y += int(size * 1.12)
    return _jpeg(img)


def render_moment(photo: Image.Image, kicker: str) -> bytes:
    """Carousel slide 1 — the shot. This is the grid thumbnail."""
    img = photo.convert("RGBA")
    draw = ImageDraw.Draw(img)
    _hairline(draw, FEED_W, FEED_H, 22)
    kfont = _ff(_UI, 26)
    _tracked(img, (48, 52), kicker, kfont, GOLD, tracking=5, anchor="lt", shadow=2)
    mark = _ff(_UI, 22)
    _shadow_text(img, (FEED_W - 48, FEED_H - 44), "1 / 3", mark, MUTED, anchor="rt", shadow=2)
    return _jpeg(img)


def render_sidebar(photo: Image.Image, kicker: str, hook: str) -> bytes:
    """Carousel slide 2 — take on a left panel over the same frame."""
    img = photo.convert("RGBA")
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    fade_end = 560
    for x in range(fade_end):
        t = 1.0 - (x / fade_end)
        a = int(232 * (t ** 0.55))
        sd.line([(x, 0), (x, FEED_H)], fill=(7, 8, 10, a))
    img.alpha_composite(shade)
    draw = ImageDraw.Draw(img)
    kfont = _ff(_UI, 26)
    _tracked(img, (48, 80), kicker, kfont, GOLD, tracking=6, anchor="lt", shadow=2)
    draw.line([(48, 122), (120, 122)], fill=GOLD, width=2)
    font, lines, size = _fit_lines(draw, hook, 480, 5, 50, 32)
    y = 160
    for ln in lines:
        _shadow_text(img, (48, y), ln, font, INK, anchor="lt", shadow=3)
        y += int(size * 1.18)
    mark = _ff(_UI, 22)
    _shadow_text(img, (FEED_W - 48, FEED_H - 44), "2 / 3", mark, MUTED, anchor="rt", shadow=2)
    return _jpeg(img)


def render_fight(kicker: str, question: str, hook: str) -> bytes:
    """Carousel slide 3 — the argument. Dark, gold, two pills."""
    img = Image.new("RGB", (FEED_W, FEED_H), DARK).convert("RGBA")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, FEED_W - 40, FEED_H - 40], outline=GOLD, width=2)
    draw.rectangle([52, 52, FEED_W - 52, FEED_H - 52], outline=(42, 39, 28), width=1)
    kfont = _ff(_UI, 30)
    _tracked(img, (FEED_W // 2, 150), kicker, kfont, GOLD, tracking=8, anchor="mt", shadow=1)
    draw.line([(FEED_W // 2 - 40, 194), (FEED_W // 2 + 40, 194)], fill=GOLD, width=2)
    label = _ff(_UI, 26)
    _shadow_text(img, (FEED_W // 2, 250), "YOUR CALL", label, MUTED, anchor="mt", shadow=1)
    text = question or hook
    font, lines, size = _fit_lines(draw, text, FEED_W - 160, 5, 68, 36)
    line_h = int(size * 1.18)
    block = line_h * len(lines) + 130
    y = max(340, (FEED_H - block) // 2)
    for ln in lines:
        _shadow_text(img, (FEED_W // 2, y), ln, font, INK, anchor="mt", shadow=2)
        y += line_h
    left, right = _pills(question or hook)
    _draw_pills(img, left, right, min(y + 48, FEED_H - 200))
    mark = _ff(_UI, 22)
    _shadow_text(img, (FEED_W - 72, FEED_H - 72), "3 / 3", mark, MUTED, anchor="rt", shadow=1)
    return _jpeg(img)


def render_story(photo: Image.Image, kicker: str, question: str, hook: str) -> bytes:
    """9:16 story. The question is the whole post — Stories ignore captions."""
    frame = smart_crop(photo, STORY_W, STORY_H, bias="auto")
    img = _apply_bottom_dark(frame, 0.52, 235).convert("RGBA")
    draw = ImageDraw.Draw(img)
    kfont = _ff(_UI, 32)
    _tracked(img, (STORY_W // 2, 1140), kicker, kfont, GOLD, tracking=8, anchor="mt", shadow=2)
    draw.line([(STORY_W // 2 - 44, 1188), (STORY_W // 2 + 44, 1188)], fill=GOLD, width=2)
    text = question or hook
    font, lines, size = _fit_lines(draw, text, STORY_W - 140, 4, 64, 36)
    y = 1220
    for ln in lines:
        _shadow_text(img, (STORY_W // 2, y), ln, font, INK, anchor="mt", shadow=3)
        y += int(size * 1.16)
    left, right = _pills(question or hook)
    # story is taller — reuse pill drawer with a local y, but _draw_pills uses FEED_W
    # Draw story pills here so they're centered on 1080.
    _draw_pills(img, left, right, min(y + 40, STORY_H - 220))
    return _jpeg(img)


def pick_style(story_id: str, last_styles: list[str], has_question: bool, flourish: str) -> str:
    rng = random.Random(int(hashlib.sha1((story_id or "x").encode()).hexdigest()[:12], 16))
    weights = {
        "carousel": 28 if has_question else 11,
        "cover": 18,
        "broadcast": 16,
        "split": 14,
        "editorial": 12,
        "scorebug": 10,
        "clean": 14,
    }
    recent = last_styles or []
    last = recent[-1] if recent else None
    for s in recent[-3:]:
        if s in weights:
            weights[s] = max(4, weights[s] - 14)
    if last == "clean":
        weights["cover"] += 10
        weights["carousel"] += 8
        weights["broadcast"] += 6
    if last == "cover":
        weights["clean"] += 10
        weights["editorial"] += 6
        weights["cover"] = max(3, weights["cover"] - 8)
    if last == "carousel":
        weights["clean"] += 8
        weights["scorebug"] += 6
    names = list(weights)
    w = [weights[n] for n in names]
    return rng.choices(names, weights=w, k=1)[0]


def build_ig_pack(
    still_bytes: bytes,
    copy: dict,
    story: dict,
    flourish: str = "none",
    last_styles: list[str] | None = None,
) -> dict | None:
    if is_weak_still(still_bytes):
        print("  ig      weak still — skipping Instagram")
        return None
    try:
        src = Image.open(io.BytesIO(still_bytes)).convert("RGB")
    except Exception:
        return None
    take, question = split_take(copy, story)
    kicker = _kicker(story)
    hook = overlay_hook(copy, take, question, kicker)
    q = overlay_question(copy, question)
    sid = str(story.get("id") or "ig")
    bias = _bias_for(sid)
    photo = smart_crop(src, FEED_W, FEED_H, bias=bias)
    style = pick_style(sid, last_styles or [], bool(q), flourish)
    mark = cover_mark(hook)

    if style == "clean":
        slides = [render_clean(photo, kicker)]
    elif style == "editorial":
        slides = [render_editorial(photo, kicker, hook)]
    elif style == "cover":
        slides = [render_cover(photo, kicker, mark, q)]
    elif style == "split":
        slides = [render_split(photo, kicker, hook, q)]
    elif style == "scorebug":
        slides = [render_scorebug(photo, kicker, hook)]
    elif style == "carousel":
        slides = [
            render_moment(photo, kicker),
            render_sidebar(photo, kicker, hook),
            render_fight(kicker, q, hook),
        ]
    else:
        slides = [render_broadcast(photo, kicker, hook, q, show_q=bool(q))]
        style = "broadcast"

    story_bytes = None
    if flourish == "story":
        story_bytes = render_story(src, kicker, q, hook)

    out_dir = Path(__file__).resolve().parent / "out" / "ig"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, blob in enumerate(slides):
        (out_dir / f"{sid}-{style}-{i+1}.jpg").write_bytes(blob)
    if story_bytes:
        (out_dir / f"{sid}-story.jpg").write_bytes(story_bytes)
    print(f"  ig      {style} · {len(slides)} slide(s)" + (" + story" if story_bytes else ""))
    return {
        "style": style,
        "slides": slides,
        "story": story_bytes,
        "take_on_image": style != "clean",
        "kicker": kicker,
        "hook": hook,
    }


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    stills = here / "out" / "stills"
    dest = here / "out" / "ig"
    dest.mkdir(parents=True, exist_ok=True)

    def load(p: Path) -> bytes:
        return p.read_bytes()

    samples = [
        (
            "scottie",
            stills / "news-anotherroundofscottiebythenumbersweputacaponthepgatourseasononlastnightsliveshow.jpg",
            "PGA TOUR",
            "Scottie is not like us",
            "What actually counts as a blown shot for these guys?",
        ),
        (
            "dunes",
            stills / "x-2094832930766119304.jpg",
            "NO LAYING UP",
            "1:00 p.m. still hits different",
            "Would you take this tee time?",
        ),
        (
            "fox",
            stills / "news-worththewaitwelcometotheintlteamryanfoxgolferpresidentscupintlteam.jpg",
            "PRESIDENTS CUP",
            "Worth the wait",
            "Fox over a veteran — right call or snub?",
        ),
        (
            "channel",
            stills / "yt-LDw2u1zYHSM.jpg",
            "GOLF CHANNEL",
            "The room just got quiet",
            "Which pick ages worse?",
        ),
        (
            "minwoo",
            stills / "x-2094793561065586794.jpg",
            "PRESIDENTS CUP",
            "This one is personal",
            "Does the Cup still mean more?",
        ),
    ]

    # Prefer a downloaded Shorts thumb if present.
    extra = here / "out" / "ig" / "_src-scottie.jpg"
    if extra.exists():
        samples[0] = (
            "scottie",
            extra,
            "PGA TOUR",
            "Scottie is not like us",
            "What actually counts as a blown shot for these guys?",
        )

    styles_fn = {
        "clean": lambda ph, k, h, q: render_clean(ph, k),
        "broadcast": lambda ph, k, h, q: render_broadcast(ph, k, h, q, True),
        "editorial": lambda ph, k, h, q: render_editorial(ph, k, h),
        "cover": lambda ph, k, h, q: render_cover(ph, k, cover_mark(h), q),
        "split": lambda ph, k, h, q: render_split(ph, k, h, q),
        "scorebug": lambda ph, k, h, q: render_scorebug(ph, k, h),
        "moment": lambda ph, k, h, q: render_moment(ph, k),
        "sidebar": lambda ph, k, h, q: render_sidebar(ph, k, h),
        "fight": lambda ph, k, h, q: render_fight(k, q, h),
    }

    # One of each layout, rotating sources so the set looks like a real grid.
    grid = [
        ("scottie", "cover"),
        ("dunes", "clean"),
        ("fox", "broadcast"),
        ("channel", "split"),
        ("minwoo", "editorial"),
        ("scottie", "scorebug"),
        ("dunes", "moment"),
        ("dunes", "sidebar"),
        ("dunes", "fight"),
        ("fox", "story"),
    ]
    for name, style in grid:
        row = next(s for s in samples if s[0] == name)
        _, path, kicker, hook, q = row
        if not path.exists():
            print("missing", path)
            continue
        src = Image.open(io.BytesIO(load(path))).convert("RGB")
        if style == "story":
            blob = render_story(src, kicker, q, hook)
            (dest / f"demo-{name}-story.jpg").write_bytes(blob)
            print("wrote", f"demo-{name}-story.jpg", len(blob))
            continue
        photo = smart_crop(src, FEED_W, FEED_H, bias="auto")
        blob = styles_fn[style](photo, kicker, hook, q)
        (dest / f"demo-{name}-{style}.jpg").write_bytes(blob)
        print("wrote", f"demo-{name}-{style}.jpg", len(blob))
