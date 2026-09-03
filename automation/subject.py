#!/usr/bin/env python3
"""Find the actual subject in a still so 4:5 crops don't cut heads off."""
from __future__ import annotations

from PIL import Image, ImageFilter

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    _CV = True
except Exception:
    cv2 = None  # type: ignore
    np = None  # type: ignore
    _CV = False


def _faces_cv(im: Image.Image) -> list[tuple[int, int, int, int]]:
    if not _CV or not hasattr(cv2, "CascadeClassifier"):
        return []
    try:
        g = cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2GRAY)
        h, w = g.shape
        scale = 1.0
        if max(w, h) > 900:
            scale = 900 / max(w, h)
            g = cv2.resize(g, (int(w * scale), int(h * scale)))
        xml = getattr(cv2, "data", None)
        path = (xml.haarcascades + "haarcascade_frontalface_default.xml") if xml else ""
        if not path:
            return []
        cascade = cv2.CascadeClassifier(path)
        if cascade.empty():
            return []
        raw = cascade.detectMultiScale(g, scaleFactor=1.12, minNeighbors=5, minSize=(28, 28))
    except Exception:
        return []
    out = []
    for x, y, fw, fh in raw:
        out.append((int(x / scale), int(y / scale), int(fw / scale), int(fh / scale)))
    return out


def _skin_peak(im: Image.Image) -> tuple[float, float, float]:
    """Normalized (cx, cy, mass) of skin-ish pixels. Fallback when no face box."""
    small = im.convert("RGB").resize((80, 80), Image.Resampling.BILINEAR)
    xs, ys, n = 0.0, 0.0, 0
    for y in range(80):
        for x in range(80):
            r, g, b = small.getpixel((x, y))
            if r > 95 and g > 40 and b > 20 and r > g and r > b and (r - g) > 8 and max(r, g, b) - min(r, g, b) > 15:
                xs += x
                ys += y
                n += 1
    if n < 40:
        return 0.5, 0.45, 0.0
    return xs / n / 80.0, ys / n / 80.0, n / 6400.0


def _edge_peak(im: Image.Image) -> tuple[float, float]:
    g = im.convert("L").resize((48, 48), Image.Resampling.BILINEAR).filter(ImageFilter.FIND_EDGES)
    px = list(g.getdata())
    best, bx, by = -1, 24, 20
    i = 0
    for y in range(48):
        for x in range(48):
            v = px[i]
            i += 1
            # Ignore outer 2px (letterbox edges)
            if x < 2 or x > 45 or y < 2 or y > 45:
                continue
            if v > best:
                best, bx, by = v, x, y
    return bx / 48.0, by / 48.0


def analyze(im: Image.Image) -> dict:
    """Where the subject is, and what kind of still this is."""
    im = im.convert("RGB")
    w, h = im.size
    faces = _faces_cv(im)
    sx, sy, skin = _skin_peak(im)
    ex, ey = _edge_peak(im)
    if faces:
        faces = sorted(faces, key=lambda b: b[2] * b[3], reverse=True)
        x, y, fw, fh = faces[0]
        cx = (x + fw / 2) / w
        cy = (y + fh / 2) / h
        face_frac = (fw * fh) / max(1, w * h)
    else:
        # Blend skin + edges. Skin wins if there's a real mass of it.
        if skin > 0.04:
            cx, cy = sx, sy
        else:
            cx, cy = (sx * 0.35 + ex * 0.65), (sy * 0.35 + ey * 0.65)
        face_frac = 0.0
    # Burned-in title chips live in the upper third and steal the edge peak.
    top = im.crop((int(w * 0.12), int(h * 0.04), int(w * 0.88), int(h * 0.36))).resize((48, 16))
    chip = 0
    for r, g, b in top.getdata():
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn > 48 and mx > 90 and not (g > r + 12 and g > b + 12):
            chip += 1
    if chip > 50 and cy < 0.40:
        cy = min(0.62, cy + 0.28)
    talking_head = bool(faces) and face_frac > 0.10 and cy < 0.62
    # Title cards: huge flat color + little photographic grain.
    tiny = im.resize((32, 32), Image.Resampling.BILINEAR)
    cols = list(tiny.getdata())
    avg = tuple(sum(c[i] for c in cols) / len(cols) for i in range(3))
    var = sum((c[0] - avg[0]) ** 2 + (c[1] - avg[1]) ** 2 + (c[2] - avg[2]) ** 2 for c in cols) / len(cols)
    title_card = var < 900 and face_frac < 0.04
    # Grid-safe if subject would land in the center square of a 4:5.
    grid_ok = 0.22 <= cy <= 0.72 and 0.18 <= cx <= 0.82
    action = (not talking_head) and (not title_card) and face_frac < 0.16
    return {
        "cx": float(min(0.92, max(0.08, cx))),
        "cy": float(min(0.92, max(0.08, cy))),
        "face_frac": float(face_frac),
        "faces": len(faces),
        "talking_head": talking_head,
        "title_card": title_card,
        "grid_ok": grid_ok,
        "action": action,
        "skin": float(skin),
    }


def score_still(im: Image.Image) -> float:
    """Higher is a better Instagram frame."""
    a = analyze(im)
    s = 40.0
    s += 28 if a["faces"] else 0
    s += 18 if a["grid_ok"] else -12
    s += 10 if a["action"] else 0
    s -= 25 if a["title_card"] else 0
    s -= 8 if a["talking_head"] else 0
    w, h = im.size
    s += 8 if min(w, h) >= 640 else 0
    s += 6 if w * h >= 800 * 600 else 0
    return s


def crop_around(im: Image.Image, tw: int, th: int, cx: float, cy: float, dest_cy: float = 0.42) -> Image.Image:
    """Fill tw×th with the subject at dest_cy in the output (grid-friendly)."""
    im = im.convert("RGB")
    src_r = im.width / max(1, im.height)
    dst_r = tw / th
    if src_r > dst_r:
        nw = int(im.height * dst_r)
        extra = im.width - nw
        left = int(cx * im.width - nw / 2)
        left = max(0, min(extra, left))
        im = im.crop((left, 0, left + nw, im.height))
    elif src_r < dst_r:
        nh = int(im.width / dst_r)
        extra = im.height - nh
        top = int(cy * im.height - dest_cy * nh)
        top = max(0, min(extra, top))
        im = im.crop((0, top, im.width, top + nh))
    return im.resize((tw, th), Image.Resampling.LANCZOS)
