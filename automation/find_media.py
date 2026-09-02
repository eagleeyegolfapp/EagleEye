#!/usr/bin/env python3
"""
Real, openly licensed images that match the post subject.
Never skip Instagram — search hard, then a golf still, never a blank.
No AI video. No ripped broadcasts. No Getty.
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.parse
import urllib.request

CTX = ssl.create_default_context()
UA = "EagleEyeGolf-media/1.0 (+https://eagleeyelabsllc.com/golf/)"

OPEN_LICENSES = "cc0,pdm,by"
STOP = {
    "the", "this", "that", "with", "from", "only", "will", "just", "really",
    "posted", "watch", "official", "video", "golf", "new", "make", "makes",
    "into", "over", "after", "about", "their", "your", "what", "when",
}
OFF_TOPIC = re.compile(
    r"\b(hockey|tennis|basketball|soccer|football|baseball|nfl|nba|nhl|mlb|"
    r"volleyball|lacrosse|cricket|rugby|wrestling|boxing|ufc|nascar|"
    r"winston cup|thunderbird|racing|motocross|skoal|volkswagen|beetle|renault|"
    r"swimming|marathon|esports|fortnite|console|war college|cake pop)\b",
    re.I,
)
WEAK = {
    "cup", "open", "tour", "round", "like", "team", "news", "pro", "easy",
    "way", "special", "selection", "roster", "made", "post", "switch",
}
GOLFISH = re.compile(
    r"\b(golf|golfer|golfing|pga|lpga|fairway|bunker|flagstick|putt|"
    r"masters|ryder cup|solheim|medinah|links course|caddie|divot|"
    r"birdie|bogey|driver|wedge|tee box|golf course|putting green)\b",
    re.I,
)
EVENTS = (
    "Presidents Cup",
    "Ryder Cup",
    "Tour Championship",
    "FedEx Cup",
    "Masters",
    "Open Championship",
    "PGA Championship",
    "U.S. Open",
    "US Open",
    "LPGA",
    "East Lake",
    "Medinah",
    "Solheim Cup",
    "TGL",
    "St Andrews",
    "Pebble Beach",
    "Augusta",
)
SCENIC = (
    "golf fairway",
    "golf course landscape",
    "golf green flagstick",
    "golf bunker sand",
    "golf tee box",
    "golf links scotland",
    "putting green golf",
)
WIKI_CATS = (
    "Golf_courses",
    "Golf",
    "Golf_courses_in_the_United_States",
    "Golf_in_Scotland",
)
# Last-resort CC/PD golf photographs on Wikimedia Commons. Credit still applied.
CURATED = (
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/1c/Golf_and_tee.jpg",
        "title": "Golf and tee",
        "creator": "unknown",
        "license": "cc0",
        "source": "wikimedia",
        "landing": "https://commons.wikimedia.org/wiki/File:Golf_and_tee.jpg",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/76/11_Golf_Practice_Facilities.jpg",
        "title": "Golf practice facilities",
        "creator": "Wikimedia Commons photographer",
        "license": "cc by-sa 4.0",
        "source": "wikimedia",
        "landing": "https://commons.wikimedia.org/wiki/File:11_Golf_Practice_Facilities.jpg",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/6/6a/201701_Golf_Course_at_DMK.jpg",
        "title": "Golf course",
        "creator": "Wikimedia Commons photographer",
        "license": "cc by-sa 4.0",
        "source": "wikimedia",
        "landing": "https://commons.wikimedia.org/wiki/File:201701_Golf_Course_at_DMK.jpg",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/a8/2006-09-11_Golf_%280%29.JPG",
        "title": "Golf hole",
        "creator": "Wikimedia Commons photographer",
        "license": "cc by-sa 3.0",
        "source": "wikimedia",
        "landing": "https://commons.wikimedia.org/wiki/File:2006-09-11_Golf_(0).JPG",
    },
    {
        "url": "https://upload.wikimedia.org/wikipedia/commons/4/44/1957_Caltex_Tournament.jpg",
        "title": "Golf tournament",
        "creator": "Wikimedia Commons photographer",
        "license": "cc by-sa 3.0",
        "source": "wikimedia",
        "landing": "https://commons.wikimedia.org/wiki/File:1957_Caltex_Tournament.jpg",
    },
)

_CACHE: dict[str, dict | None] = {}


def _get(url: str, timeout: int = 20) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        print(f"  media search fail {url[:80]}: {e}")
        return None


def _hit_blob(hit: dict) -> str:
    tags = " ".join(
        t.get("name", "") if isinstance(t, dict) else str(t) for t in (hit.get("tags") or [])
    )
    return " ".join(
        [str(hit.get("title") or ""), str(hit.get("creator") or ""), tags]
    )


def subject_queries(story: dict) -> list[str]:
    bits = [
        story.get("creator") or "",
        story.get("video_channel") or "",
        story.get("headline") or "",
        story.get("who") or "",
        story.get("event") or "",
        story.get("course") or "",
    ]
    text = " ".join(bits)
    names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text)
    words = [
        w for w in re.findall(r"[A-Za-z]{4,}", text)
        if w.lower() not in STOP
    ]
    q: list[str] = []
    for token in EVENTS:
        if token.lower() in text.lower():
            q.append(f"{token} golf")
            q.append(token)
    for n in names:
        q.append(f"{n} golf")
        last = n.split()[-1]
        if last.lower() not in STOP:
            q.append(f"{last} golf")
    if story.get("creator"):
        q.append(f"{story['creator']} golf")
    topical = [w for w in words if w.lower() not in {x.lower() for x in " ".join(q).split()}]
    if topical:
        q.append("golf " + " ".join(topical[:3]))
    q.extend(SCENIC)
    seen, out = set(), []
    for item in q:
        k = item.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(item.strip())
    return out[:10] or list(SCENIC)


def _relevant(hit: dict, query: str, scenic: bool = False) -> bool:
    blob = _hit_blob(hit)
    if OFF_TOPIC.search(blob) and not GOLFISH.search(blob):
        return False
    if GOLFISH.search(blob):
        return True
    if scenic:
        return False
    caps = re.findall(r"[A-Z][a-z]+", query)
    if len(caps) >= 2 and all(n.lower() in blob.lower() for n in caps[:2]):
        return True
    tokens = [
        t for t in re.findall(r"[a-z]{3,}", query.lower())
        if t not in STOP and t not in WEAK
    ]
    if not tokens:
        return bool(GOLFISH.search(blob))
    return sum(1 for t in tokens if t in blob.lower()) >= max(1, (len(tokens) + 1) // 2)


def _pack_openverse(hit: dict, query: str) -> dict:
    return {
        "url": hit.get("url") or "",
        "title": hit.get("title") or query,
        "creator": hit.get("creator") or "unknown",
        "license": (hit.get("license") or "").lower(),
        "license_url": hit.get("license_url") or "",
        "attribution": hit.get("attribution") or "",
        "source": hit.get("source") or "openverse",
        "landing": hit.get("foreign_landing_url") or "",
        "query": query,
    }


def openverse_search(query: str, scenic: bool = False) -> dict | None:
    key = f"ov:{query}:{int(scenic)}"
    if key in _CACHE:
        return _CACHE[key]
    for page in (1, 2):
        qs = urllib.parse.urlencode(
            {
                "q": query,
                "license": OPEN_LICENSES,
                "license_type": "commercial",
                "category": "photograph",
                "page": str(page),
                "page_size": "20",
                "mature": "false",
            }
        )
        data = _get(f"https://api.openverse.org/v1/images/?{qs}")
        if not isinstance(data, dict):
            continue
        for hit in data.get("results") or []:
            url = hit.get("url") or ""
            if not url.startswith("https://"):
                continue
            if not _relevant(hit, query, scenic=scenic):
                continue
            packed = _pack_openverse(hit, query)
            _CACHE[key] = packed
            return packed
    _CACHE[key] = None
    return None


def wikimedia_search(query: str, scenic: bool = False) -> dict | None:
    key = f"wiki:{query}:{int(scenic)}"
    if key in _CACHE:
        return _CACHE[key]
    qs = urllib.parse.urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": "6",
            "gsrlimit": "12",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "format": "json",
        }
    )
    data = _get(f"https://commons.wikimedia.org/w/api.php?{qs}")
    if not isinstance(data, dict):
        _CACHE[key] = None
        return None
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = (info.get("url") or "").split("?")[0]
        mime = (info.get("mime") or "").lower()
        if not url.startswith("https://"):
            continue
        if not any(x in mime for x in ("jpeg", "jpg", "png", "webp")):
            continue
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value") or ""
        artist = (meta.get("Artist") or {}).get("value") or ""
        artist = re.sub(r"<[^>]+>", "", artist)
        title = page.get("title") or query
        probe = {"title": title, "creator": artist, "tags": []}
        if not _relevant(probe, query, scenic=scenic):
            continue
        packed = {
            "url": url,
            "title": title,
            "creator": artist or "Wikimedia Commons",
            "license": lic.lower(),
            "license_url": (meta.get("LicenseUrl") or {}).get("value") or "",
            "attribution": f"{title} — {artist} ({lic})".strip(" —"),
            "source": "wikimedia",
            "landing": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title)}",
            "query": query,
        }
        _CACHE[key] = packed
        return packed
    _CACHE[key] = None
    return None


def wikimedia_category(cat: str) -> list[dict]:
    qs = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{cat}",
            "cmtype": "file",
            "cmlimit": "20",
            "format": "json",
        }
    )
    data = _get(f"https://commons.wikimedia.org/w/api.php?{qs}")
    titles = [
        x.get("title") or ""
        for x in ((data or {}).get("query") or {}).get("categorymembers") or []
        if (x.get("title") or "").lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ]
    if not titles:
        return []
    tqs = urllib.parse.urlencode(
        {
            "action": "query",
            "titles": "|".join(titles[:12]),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime|size",
            "format": "json",
        }
    )
    info = _get(f"https://commons.wikimedia.org/w/api.php?{tqs}")
    out = []
    pages = ((info or {}).get("query") or {}).get("pages") or {}
    for page in pages.values():
        ii = (page.get("imageinfo") or [{}])[0]
        url = (ii.get("url") or "").split("?")[0]
        mime = (ii.get("mime") or "").lower()
        if not url.startswith("https://"):
            continue
        if not any(x in mime for x in ("jpeg", "jpg", "png", "webp")):
            continue
        meta = ii.get("extmetadata") or {}
        title = page.get("title") or cat
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value") or "")
        lic = (meta.get("LicenseShortName") or {}).get("value") or "cc by-sa"
        probe = {"title": title, "creator": artist, "tags": [{"name": "golf"}]}
        if OFF_TOPIC.search(_hit_blob(probe)) and not GOLFISH.search(_hit_blob(probe)):
            continue
        out.append(
            {
                "url": url,
                "title": title,
                "creator": artist or "Wikimedia Commons",
                "license": lic.lower(),
                "license_url": (meta.get("LicenseUrl") or {}).get("value") or "",
                "attribution": f"{title} — {artist} ({lic})".strip(" —"),
                "source": "wikimedia",
                "landing": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title)}",
                "query": f"Category:{cat}",
            }
        )
    return out


def _curated(story: dict) -> dict:
    seed = (story.get("id") or story.get("headline") or "golf").encode()
    idx = int(hashlib.sha1(seed).hexdigest(), 16) % len(CURATED)
    hit = dict(CURATED[idx])
    hit["query"] = "curated-golf"
    return hit


def find_subject_image(story: dict) -> dict:
    """Always return a rights-safe golf photograph. Prefer subject match, never skip."""
    queries = subject_queries(story)
    specific = [q for q in queries if q not in SCENIC]
    scenic = [q for q in queries if q in SCENIC]
    for q in specific:
        hit = openverse_search(q, scenic=False) or wikimedia_search(q, scenic=False)
        if hit:
            print(f"  ig still  {hit['source']} / {hit['license']} / q={q!r}")
            return hit
    for q in scenic:
        hit = openverse_search(q, scenic=True) or wikimedia_search(q, scenic=True)
        if hit:
            print(f"  ig still  scenic {hit['source']} / {hit['license']} / q={q!r}")
            return hit
    for cat in WIKI_CATS:
        pool = wikimedia_category(cat)
        if pool:
            seed = (story.get("id") or story.get("headline") or cat).encode()
            hit = pool[int(hashlib.sha1(seed).hexdigest(), 16) % len(pool)]
            print(f"  ig still  category {cat} / {hit['license']}")
            return hit
    hit = _curated(story)
    print(f"  ig still  curated golf still / {hit['license']}")
    return hit


def credit_line(hit: dict | None) -> str:
    if not hit:
        return ""
    lic = (hit.get("license") or "").lower()
    if lic in {"cc0", "pdm", "public domain", "pd"}:
        return ""
    attr = hit.get("attribution") or ""
    if attr:
        return f"Photo: {attr}"
    who = hit.get("creator") or "photographer"
    return f"Photo: {who} ({hit.get('license')})"
