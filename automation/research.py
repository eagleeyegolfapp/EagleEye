#!/usr/bin/env python3
"""Live golf news + official creator videos. Link the file; never download it."""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from urllib.parse import urlparse
import urllib.parse

from story_quality import fingerprint, keep_title, score_candidate, story_keys, x_status_id, youtube_id_from_url

CTX = ssl.create_default_context()
NY = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
_YT_CACHE: dict[str, list] = {}
_RSS_CACHE: dict[str, list] = {}
_X_CACHE: dict[str, list] = {}
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
MRSS = "{http://search.yahoo.com/mrss/}"
ALLOW = {
    "pgatour.com",
    "www.pgatour.com",
    "espn.com",
    "www.espn.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "vimeo.com",
    "www.vimeo.com",
    "x.com",
    "twitter.com",
    "www.twitter.com",
    "golfdigest.com",
    "www.golfdigest.com",
    "apnews.com",
    "www.apnews.com",
    "lpga.com",
    "www.lpga.com",
    "golf.com",
    "www.golf.com",
    "golfmonthly.com",
    "www.golfmonthly.com",
    "golfdigest.com",
    "www.golfdigest.com",
    "thefriedegg.com",
    "nolayingup.com",
    "www.nolayingup.com",
    "mygolfspy.com",
    "www.mygolfspy.com",
    "todays-golfer.com",
    "www.todays-golfer.com",
    "si.com",
    "www.si.com",
    "theopen.com",
    "www.theopen.com",
    "usga.org",
    "www.usga.org",
    "bbc.co.uk",
    "www.bbc.co.uk",
    "bbc.com",
    "www.bbc.com",
    "nytimes.com",
    "www.nytimes.com",
    "golfwrx.com",
    "www.golfwrx.com",
    "bunkered.co.uk",
    "www.bunkered.co.uk",
    "australiangolfdigest.com.au",
    "www.australiangolfdigest.com.au",
}


def host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ALLOW or host.removeprefix("www.") in ALLOW


def http_get(url: str, timeout: int = 25) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
            return resp.status, resp.read(700_000).decode(
                resp.headers.get_content_charset() or "utf-8", errors="replace"
            )
    except Exception as e:  # noqa: BLE001
        print(f"  GET fail {url}: {e}")
        return 0, ""


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):  # noqa: ANN001
        if self.skip:
            return
        t = " ".join(data.split())
        if t:
            self.parts.append(t)


def page_text(html: str) -> str:
    p = _Text()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html)
    return " ".join(p.parts)


def youtube_rss(channel_id: str) -> list[dict]:
    if not channel_id:
        return []
    if channel_id in _YT_CACHE:
        return _YT_CACHE[channel_id]
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    code, xml = http_get(url)
    if code != 200 or not xml:
        _YT_CACHE[channel_id] = []
        return []
    root = ET.fromstring(xml)
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        title = (entry.findtext(f"{ATOM}title") or "").strip()
        vid = (entry.findtext(f"{YT}videoId") or "").strip()
        published = (entry.findtext(f"{ATOM}published") or "").strip()
        author = entry.find(f"{ATOM}author")
        name = (author.findtext(f"{ATOM}name") if author is not None else "") or ""
        if not vid:
            continue
        group = entry.find(f"{MRSS}group")
        duration = 0
        desc = ""
        thumb = ""
        if group is not None:
            desc = (group.findtext(f"{MRSS}description") or "").strip()[:400]
            content = group.find(f"{MRSS}content")
            if content is not None:
                try:
                    duration = int(float(content.get("duration") or 0))
                except ValueError:
                    duration = 0
            tn = group.find(f"{MRSS}thumbnail")
            if tn is not None:
                thumb = (tn.get("url") or "").strip()
        is_short = 0 < duration <= 90
        video_url = (
            f"https://www.youtube.com/shorts/{vid}"
            if is_short
            else f"https://www.youtube.com/watch?v={vid}"
        )
        out.append(
            {
                "title": title,
                "video_id": vid,
                "video_url": video_url,
                "published": published,
                "channel": name,
                "excerpt": desc,
                "duration": duration,
                "is_short": is_short,
                "thumb": thumb or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            }
        )
    _YT_CACHE[channel_id] = out
    return out


def fetch_link_story(url: str, cfg: dict | None = None) -> dict:
    """Turn a pasted YouTube / Vimeo / X / article URL into a community story."""
    url = (url or "").strip()
    if not url.startswith("http"):
        raise RuntimeError("Paste a full http(s) link.")
    title, creator, thumb = "", "", ""
    yid = youtube_id_from_url(url)
    if yid:
        url = f"https://www.youtube.com/watch?v={yid}"
        oembed = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url, safe='')}&format=json"
        code, raw = http_get(oembed)
        if code == 200 and raw.startswith("{"):
            try:
                data = json.loads(raw)
                title = data.get("title") or ""
                creator = data.get("author_name") or ""
                thumb = data.get("thumbnail_url") or ""
            except json.JSONDecodeError:
                pass
    elif "vimeo.com" in url:
        oembed = f"https://vimeo.com/api/oembed.json?url={urllib.parse.quote(url, safe='')}"
        code, raw = http_get(oembed)
        if code == 200 and raw.startswith("{"):
            try:
                data = json.loads(raw)
                title = data.get("title") or ""
                creator = data.get("author_name") or ""
                thumb = data.get("thumbnail_url") or ""
            except json.JSONDecodeError:
                pass
    if not title:
        code, html = http_get(url)
        if code == 200:
            m = re.search(r"<title>([^<]+)</title>", html or "", re.I)
            title = (m.group(1) if m else "").strip()
            embeds = extract_embeds(html or "")
            if embeds and "youtube" not in url and "vimeo" not in url:
                url = embeds[0]
                yid = youtube_id_from_url(url)
    title = re.sub(r"\s+", " ", title).replace(" - YouTube", "").strip() or "This clip"
    x_handle, ig_handle = "", ""
    for ch in (cfg or {}).get("community_channels") or []:
        n = (ch.get("name") or "").lower()
        if creator and creator.lower() in n or n and n in creator.lower():
            x_handle = ch.get("x_handle") or ""
            ig_handle = ch.get("ig_handle") or ""
            break
    is_short = "/shorts/" in url
    return {
        "id": f"link-{yid or str(abs(hash(url)))[-10:]}",
        "lane": "community",
        "headline": title[:180],
        "creator": creator,
        "article_url": url,
        "video_url": url,
        "video_title": title,
        "video_channel": creator,
        "is_short": is_short,
        "x_handle": x_handle,
        "ig_handle": ig_handle,
        "thumb": thumb or (f"https://i.ytimg.com/vi/{yid}/hqdefault.jpg" if yid else ""),
        "still_prompt": f"golf, related to: {title[:80]}, no famous faces, no logos",
    }


def latest_video(channel_id: str) -> dict | None:
    items = youtube_rss(channel_id)
    return items[0] if items else None


def mark_short(item: dict) -> dict:
    vid = item.get("video_id") or ""
    if not vid:
        item["is_short"] = False
        return item
    shorts = f"https://www.youtube.com/shorts/{vid}"
    code, html = http_get(shorts)
    blob = (html or "")[:12000].lower()
    if code == 200 and "/shorts/" in blob and "video unavailable" not in blob:
        item["is_short"] = True
        item["video_url"] = shorts
        return item
    item["is_short"] = False
    return item


def extract_embeds(html: str) -> list[str]:
    """Official players that actually unfurl on X/Reddit: YouTube, Shorts, Vimeo, X."""
    found: list[str] = []
    for pat in (
        r"https://www\.youtube\.com/shorts/[\w-]+",
        r"https://youtu\.be/[\w-]+",
        r"https://www\.youtube\.com/watch\?v=[\w-]+",
        r"https://vimeo\.com/\d+",
        r"https://(?:www\.)?(?:x|twitter)\.com/[^/]+/status/\d+",
    ):
        for m in re.findall(pat, html or ""):
            if m not in found:
                found.append(m)
    return found


def pga_articles() -> list[str]:
    code, html = http_get("https://www.pgatour.com/news")
    if code != 200:
        return []
    found = re.findall(r'href="(https://www\.pgatour\.com/article/[^"#?]+)"', html)
    found += ["https://www.pgatour.com" + p for p in re.findall(r'href="(/article/[^"#?]+)"', html)]
    seen, out = set(), []
    for u in found:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out[:8]


def active_events(cfg: dict) -> list[dict]:
    today = datetime.now(NY).date()
    out = []
    for ev in cfg.get("events") or []:
        try:
            start = datetime.strptime(ev.get("start") or "", "%Y-%m-%d").date()
            end = datetime.strptime(ev.get("end") or "", "%Y-%m-%d").date()
        except ValueError:
            continue
        lead = int(ev.get("lead_days") or 10)
        if start - timedelta(days=lead) <= today <= end:
            out.append(ev)
    return out


def channel_weight(ch: dict, cfg: dict) -> int:
    w = int(ch.get("weight") or 3)
    blob = f"{ch.get('name') or ''} {ch.get('handle') or ''}".lower()
    for ev in active_events(cfg):
        for kw in ev.get("keywords") or [ev.get("name") or ""]:
            if kw and kw.lower() in blob:
                w += int(ev.get("boost") or 5)
    return max(1, w)


def weighted_sample(items: list[dict], k: int, cfg: dict) -> list[dict]:
    import random

    if len(items) <= k:
        return list(items)
    pool = [(c, channel_weight(c, cfg)) for c in items]
    picked: list[dict] = []
    for _ in range(k):
        if not pool:
            break
        total = sum(w for _, w in pool)
        r = random.uniform(0, total)
        acc = 0.0
        for i, (c, w) in enumerate(pool):
            acc += w
            if acc >= r:
                picked.append(c)
                pool.pop(i)
                break
    return picked


def parse_rss(url: str) -> list[dict]:
    if not url:
        return []
    if url in _RSS_CACHE:
        return _RSS_CACHE[url]
    code, xml = http_get(url, timeout=15)
    if code != 200 or not xml:
        _RSS_CACHE[url] = []
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        _RSS_CACHE[url] = []
        return []
    items = []
    for item in root.iter():
        tag = item.tag.lower().split("}")[-1]
        if tag != "item" and tag != "entry":
            continue
        def child(name: str) -> str:
            for ch in item:
                if ch.tag.lower().split("}")[-1] == name:
                    return (ch.text or ch.get("href") or "").strip()
            return ""
        title = child("title")
        link = child("link") or child("id")
        if not title:
            continue
        raw_desc = child("description") or child("summary")
        desc = re.sub(r"<[^>]+>", " ", raw_desc or "")
        desc = re.sub(r"\s+", " ", desc).strip()[:400]
        thumb = ""
        for ch in item:
            t = ch.tag.lower().split("}")[-1]
            if t in {"thumbnail", "image"} and (ch.get("url") or ch.get("href") or (ch.text or "").strip()):
                thumb = (ch.get("url") or ch.get("href") or (ch.text or "")).strip() or thumb
            if t in {"content", "enclosure"}:
                ctype = (ch.get("type") or ch.get("medium") or "").lower()
                href = (ch.get("url") or "").strip()
                if href and ("image" in ctype or href.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
                    thumb = href
        items.append(
            {
                "title": title[:180],
                "url": link,
                "source": url,
                "excerpt": desc,
                "published": child("pubDate") or child("published") or child("updated"),
                "thumb": thumb,
            }
        )
        if len(items) >= 8:
            break
    _RSS_CACHE[url] = items
    return items


def _twitter_account_id() -> str:
    acc = (os.environ.get("LATE_TWITTER_ACCOUNT_ID") or "").strip()
    if acc:
        return acc
    try:
        from late_client import resolve_accounts

        resolve_accounts()
    except Exception as e:  # noqa: BLE001
        print("  x search  no Late X account:", e)
        return ""
    return (os.environ.get("LATE_TWITTER_ACCOUNT_ID") or "").strip()


def recent_x_videos(handle: str, n: int = 3) -> list[dict]:
    """Official native X videos from this account. Quote/embed — never download the file."""
    handle = (handle or "").lstrip("@")
    if not handle:
        return []
    if handle in _X_CACHE:
        return _X_CACHE[handle][:n]
    acc = _twitter_account_id()
    if not acc:
        _X_CACHE[handle] = []
        return []
    try:
        from late_client import search_tweets

        tweets = search_tweets(acc, f"from:{handle} has:videos -is:retweet", limit=10)
    except Exception as e:  # noqa: BLE001
        print(f"  x search  @{handle} failed: {e}")
        _X_CACHE[handle] = []
        return []
    out: list[dict] = []
    for t in tweets:
        tid = str(t.get("id") or "")
        if not tid.isdigit():
            continue
        author = t.get("author") or {}
        uname = (author.get("username") or handle).lstrip("@")
        text = (t.get("text") or "").strip()
        title = re.sub(r"https?://\S+", "", text)
        title = re.sub(r"\s+", " ", title).strip()[:180]
        if not keep_title(title) and len(title) < 12:
            title = f"Clip from @{uname}"
        out.append(
            {
                "title": title or f"Clip from @{uname}",
                "video_url": f"https://x.com/{uname}/status/{tid}",
                "video_id": tid,
                "x_status_id": tid,
                "channel": uname,
                "is_short": False,
                "published": t.get("created") or "",
                "excerpt": text[:400],
                "has_x_video": True,
            }
        )
    _X_CACHE[handle] = out
    return out[:n]


def latest_x_post(handle: str) -> dict | None:
    vids = recent_x_videos(handle, 1)
    return vids[0] if vids else None


def x_video_handles(cfg: dict) -> list[dict]:
    """Dedupe official X handles from tours, news, and community."""
    seen: set[str] = set()
    out: list[dict] = []
    for group, default_w in (
        (cfg.get("x_accounts") or [], 8),
        (cfg.get("news_channels") or [], 8),
        (cfg.get("community_channels") or [], 6),
    ):
        for raw in group:
            handle = (raw.get("x_handle") or raw.get("handle") or "").lstrip("@")
            if not handle or handle.lower() in seen:
                continue
            seen.add(handle.lower())
            item = dict(raw)
            item["handle"] = handle
            item["x_handle"] = handle
            item["weight"] = int(raw.get("weight") or default_w)
            out.append(item)
    return out


def title_event_boost(title: str, cfg: dict) -> int:
    t = (title or "").lower()
    n = 0
    for ev in active_events(cfg):
        for kw in ev.get("keywords") or [ev.get("name") or ""]:
            if kw and kw.lower() in t:
                n += int(ev.get("boost") or 5)
    return n


def _used_set(*parts: set | list | None) -> set[str]:
    out: set[str] = set()
    for part in parts:
        if not part:
            continue
        out.update(str(x) for x in part if x)
    return out


def _already(obj: dict, used: set[str]) -> bool:
    return bool(used.intersection(story_keys(obj)))


def _pick_scored(rows: list[tuple[float, dict, dict]]) -> tuple[dict, dict]:
    import random

    live = [r for r in rows if r[0] > -50]
    rows = live or [r for r in rows if r[0] > -900] or rows
    if not rows:
        raise RuntimeError("No usable golf stories after filters.")
    rows.sort(key=lambda r: r[0], reverse=True)
    top = rows[:8]
    weights = [max(0.15, s) for s, _, _ in top]
    total = sum(weights)
    r = random.uniform(0, total)
    acc = 0.0
    for w, triple in zip(weights, top):
        acc += w
        if acc >= r:
            return triple[1], triple[2]
    return top[0][1], top[0][2]


def _resolve_article_video(page_url: str) -> tuple[str, str]:
    """Return (video_or_page, excerpt). One page fetch for the winner only."""
    if not page_url.startswith("http"):
        return page_url, ""
    if any(h in page_url for h in ("youtube.com", "youtu.be", "vimeo.com", "x.com/", "twitter.com/")):
        return page_url, ""
    _, html = http_get(page_url)
    if not html:
        return page_url, ""
    embeds = extract_embeds(html)
    video = ""
    for u in embeds:
        if "/shorts/" in u:
            video = u
            break
    if not video and embeds:
        video = embeds[0]
    excerpt = page_text(html)[:400] if html else ""
    return video or page_url, excerpt


def recent_videos(channel_id: str, n: int = 4) -> list[dict]:
    if not channel_id:
        return []
    return youtube_rss(channel_id)[: max(1, n)]


def _community_story(picked: dict, meta: dict) -> dict:
    url = picked.get("video_url") or ""
    is_x = url.startswith("https://x.com/") or url.startswith("https://twitter.com/")
    if (
        not is_x
        and picked.get("video_id")
        and not str(picked.get("video_id", "")).isdigit()
        and not picked.get("is_short")
    ):
        picked = mark_short(dict(picked))
        url = picked.get("video_url") or url
        is_x = False
    sid = picked.get("video_id") or "item"
    prefix = "x" if is_x else "yt"
    creator = (meta or {}).get("name") or picked.get("channel") or ""
    return {
        "id": f"{prefix}-{sid}",
        "lane": "community",
        "headline": (picked.get("title") or "")[:180],
        "creator": creator,
        "handle": (meta or {}).get("handle") or "",
        "article_url": url,
        "video_url": url,
        "video_title": picked.get("title") or "",
        "video_channel": picked.get("channel") or creator,
        "published": picked.get("published") or "",
        "excerpt": (picked.get("excerpt") or "")[:400],
        "is_short": bool(picked.get("is_short")),
        "x_handle": (meta or {}).get("x_handle") or (meta or {}).get("handle") or "",
        "ig_handle": (meta or {}).get("ig_handle") or "",
        "x_status_id": picked.get("x_status_id") or (sid if is_x else ""),
        "has_x_video": bool(picked.get("has_x_video") or is_x),
        "thumb": picked.get("thumb") or (
            f"https://i.ytimg.com/vi/{sid}/hqdefault.jpg" if prefix == "yt" else ""
        ),
    }


def research_news(
    cfg: dict,
    used_ids: set[str] | None = None,
    used_keys: set[str] | None = None,
    used_creators: list[str] | None = None,
) -> dict:
    """One news story, scored from RSS + official YouTube. Never frankenstein two sources."""
    used = _used_set(used_ids, used_keys)
    used_cre = {c.lower() for c in (used_creators or [])[-8:]}
    scored: list[tuple[float, dict, dict]] = []

    for feed in cfg.get("news_feeds") or []:
        src = {"name": feed.get("name") or "Golf news", "kind": "rss"}
        for item in parse_rss(feed.get("url") or ""):
            title = item.get("title") or ""
            if not keep_title(title):
                continue
            page_url = item.get("url") or ""
            blob = {
                "title": title,
                "headline": title,
                "url": page_url,
                "article_url": page_url,
                "video_url": page_url,
            }
            if _already(blob, used):
                continue
            sc = score_candidate(
                title=title,
                published=item.get("published") or "",
                weight=7,
                event_boost=title_event_boost(title, cfg),
                is_short="/shorts/" in (page_url or ""),
                creator_repeat=(src["name"] or "").lower() in used_cre,
                has_embed=any(
                    h in (page_url or "")
                    for h in ("youtu", "vimeo.com", "x.com/", "twitter.com/")
                ),
                lane="news",
            )
            cand = {
                **blob,
                "excerpt": item.get("excerpt") or "",
                "thumb": item.get("thumb") or "",
                "source": src,
                "kind": "rss",
            }
            scored.append((sc, cand, src))

    for acc in weighted_sample(x_video_handles(cfg), 8, cfg):
        src = {
            "name": acc.get("name") or acc.get("handle") or "X",
            "kind": "x",
            "x_handle": acc.get("handle") or "",
            "ig_handle": acc.get("ig_handle") or "",
        }
        for post in recent_x_videos(acc.get("handle") or "", 3):
            title = post.get("title") or ""
            if not keep_title(title):
                continue
            if _already(post, used):
                continue
            sc = score_candidate(
                title=title,
                published=post.get("published") or "",
                weight=int(acc.get("weight") or 8),
                event_boost=title_event_boost(title, cfg),
                is_short=False,
                creator_repeat=(src["name"] or "").lower() in used_cre,
                has_embed=True,
                lane="news",
                x_native=True,
            )
            cand = {
                **post,
                "headline": title,
                "url": post.get("video_url"),
                "article_url": post.get("video_url"),
                "kind": "x",
                "source": src,
            }
            scored.append((sc, cand, src))

    for ch in cfg.get("news_channels") or []:
        src = {
            "name": ch.get("name") or "PGA TOUR",
            "kind": "yt",
            "x_handle": ch.get("x_handle") or ch.get("handle") or "",
            "ig_handle": ch.get("ig_handle") or "",
        }
        for vid in recent_videos(ch.get("youtube_id") or "", 4):
            title = vid.get("title") or ""
            if not keep_title(title):
                continue
            if _already(vid, used):
                continue
            sc = score_candidate(
                title=title,
                published=vid.get("published") or "",
                weight=int(ch.get("weight") or 8),
                event_boost=title_event_boost(title, cfg),
                is_short=bool(vid.get("is_short")),
                creator_repeat=(src["name"] or "").lower() in used_cre,
                has_embed=True,
                lane="news",
            )
            cand = {
                "title": title,
                "headline": title,
                "url": vid.get("video_url"),
                "article_url": vid.get("video_url"),
                "video_url": vid.get("video_url"),
                "video_id": vid.get("video_id"),
                "excerpt": vid.get("excerpt") or "",
                "published": vid.get("published") or "",
                "is_short": bool(vid.get("is_short")),
                "channel": vid.get("channel") or src["name"],
                "thumb": vid.get("thumb") or "",
                "kind": "yt",
                "source": src,
            }
            scored.append((sc, cand, src))

    if not scored:
        raise RuntimeError("No live golf news found (RSS and official YouTube RSS both empty).")
    picked, src = _pick_scored(scored)
    video = picked.get("video_url") or picked.get("article_url") or ""
    excerpt = picked.get("excerpt") or ""
    article = picked.get("article_url") or video
    if picked.get("kind") == "rss":
        resolved, page_ex = _resolve_article_video(article)
        video = resolved
        if page_ex and len(page_ex) > len(excerpt):
            excerpt = page_ex
        if video and not host_ok(video) and not any(
            h in video for h in ("vimeo.com", "x.com/", "twitter.com/", "youtu")
        ):
            video = article
        if article and not host_ok(article):
            article = video
    yid = youtube_id_from_url(video) or youtube_id_from_url(article)
    story_id = f"yt-{yid}" if yid else "news-" + (
        fingerprint(picked.get("title") or "") or datetime.now(timezone.utc).strftime("%H%M%S")
    )
    print(f"  news pick  {src.get('name')} · {picked.get('title','')[:70]}")
    return {
        "id": story_id,
        "lane": "news",
        "headline": (picked.get("title") or "")[:180],
        "article_url": article,
        "video_url": video,
        "video_title": picked.get("title") or "",
        "video_channel": src.get("name") or picked.get("channel") or "Golf news",
        "creator": src.get("name") or picked.get("channel") or "",
        "excerpt": excerpt[:400],
        "published": picked.get("published") or "",
        "is_short": bool(picked.get("is_short")) or "/shorts/" in (video or ""),
        "x_handle": (src.get("x_handle") or "").lstrip("@"),
        "ig_handle": (src.get("ig_handle") or "").lstrip("@"),
        "thumb": picked.get("thumb") or (f"https://i.ytimg.com/vi/{yid}/hqdefault.jpg" if yid else ""),
        "x_status_id": picked.get("x_status_id") or x_status_id(video) or x_status_id(article),
        "has_x_video": bool(picked.get("has_x_video") or picked.get("kind") == "x"),
    }


def research_community(
    cfg: dict,
    used_ids: set[str] | None = None,
    used_keys: set[str] | None = None,
    used_creators: list[str] | None = None,
) -> dict:
    """Official creator video. Link it. Do not re-upload it."""
    used = _used_set(used_ids, used_keys)
    used_cre = {c.lower() for c in (used_creators or [])[-8:]}
    channels = list(cfg.get("community_channels") or [])
    sample = weighted_sample(channels, 14, cfg)
    scored: list[tuple[float, dict, dict]] = []

    for acc in weighted_sample(x_video_handles(cfg), 12, cfg):
        for post in recent_x_videos(acc.get("handle") or "", 3):
            title = post.get("title") or ""
            if not keep_title(title) or title.lower().startswith("new from @"):
                continue
            if _already(post, used):
                continue
            sc = score_candidate(
                title=title,
                published=post.get("published") or "",
                weight=int(acc.get("weight") or 8),
                event_boost=title_event_boost(title, cfg),
                is_short=False,
                creator_repeat=(acc.get("name") or acc.get("handle") or "").lower() in used_cre,
                has_embed=True,
                lane="community",
                x_native=True,
            )
            scored.append((sc, post, acc))

    for ch in sample:
        for vid in recent_videos(ch.get("youtube_id") or "", 4):
            title = vid.get("title") or ""
            if not keep_title(title):
                continue
            if _already(vid, used):
                continue
            creator = (ch.get("name") or vid.get("channel") or "").lower()
            sc = score_candidate(
                title=title,
                published=vid.get("published") or "",
                weight=int(ch.get("weight") or 3),
                event_boost=title_event_boost(title, cfg),
                is_short=bool(vid.get("is_short")),
                creator_repeat=creator in used_cre,
                has_embed=True,
                lane="community",
                x_native=False,
            )
            scored.append((sc, vid, ch))

    if not scored:
        raise RuntimeError("No community YouTube RSS items. Add channel IDs in the dashboard.")
    picked, meta = _pick_scored(scored)
    story = _community_story(picked, meta)
    print(f"  community  {story.get('creator')} · {story.get('headline','')[:70]}")
    return story
