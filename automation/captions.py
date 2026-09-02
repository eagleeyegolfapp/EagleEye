#!/usr/bin/env python3
"""Captions that get replies, not recaps."""
from __future__ import annotations

import json
import os
import random
import re
import ssl
import urllib.request

from workflow_one import twitter_len

CTX = ssl.create_default_context()
XAI = "https://api.x.ai/v1"

SYSTEM = """You write captions for a golf account people actually follow.

Goal: replies, quote-tweets, profile taps. You are not a recap bot.

Voice: a good 8-handicap in the group chat. Dry, a little mean, has a take.
NOT a brand intern. NOT "New from X:". NOT a rewritten YouTube title.

Rules:
- Do NOT restate the video/article title. React to it. Assume they can see the official clip or photo.
- First line is the hook. It has to work next to the REAL official thumbnail/player — we never invent footage.
- Never write "link in comments", "check the comments", "full video below", or "link in bio".
- Do not put URLs in twitter, twitter_thread, instagram, or poll text. The system appends the official URL on X and Reddit so the real clip unfurls.
- Community: pick a side, roast, or agree. Credit the creator by name in the sentence, not as a byline.
- News: a take, not the lede.
- About a third of posts end with a specific question golfers will argue about. Never "thoughts?" or "agree?".
- The other two thirds: land the take and stop. No question.
- Emojis: 0-2, only if they land (👀 😭 🔥 💀). No hashtag soup.
- Never mention EagleEye, App Store, unlock, subscription, ads, or download.
- Never pretend we filmed it or collab'd.
- X single tweet (twitter): under 200 characters. No URL.
- X thread (twitter_thread): array of exactly 3 tweets. 1 = hook. 2 = the take. 3 = a specific question golfers will fight about. Each under 200 characters. No URLs.
- X poll: poll_question is the question (under 180 chars, no URL). poll_options is 3 or 4 answers, EACH 25 characters max, punchy, no emoji.
- Instagram: 2-4 short lines. Same take. People are looking at the official thumbnail of that clip.
- Reddit title: debate hook, under 80 characters, no emoji dump.
- Reddit body: 1-2 sentences. Do not paste the URL; the system appends it.
- ig_first_comment: ONLY Watch/Read links if we pass them. No recap.

Return JSON only with keys: twitter, twitter_thread, poll_question, poll_options, instagram, reddit_title, reddit_body, ig_first_comment."""


def _chat(prompt: str) -> str | None:
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        return None
    model = os.environ.get("XAI_TEXT_MODEL", "grok-4")
    body = {
        "model": model,
        "temperature": 0.95,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(
        f"{XAI}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45, context=CTX) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        print(f"  grok copy failed: {e}")
        return None


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def fallback(story: dict, ask: bool = False) -> dict:
    video = story.get("video_url") or story.get("article_url") or ""
    headline = (story.get("headline") or "golf being golf").rstrip(".")
    creator = story.get("creator") or story.get("video_channel") or ""
    if story.get("lane") == "community":
        twitter = f"{creator} really posted this" if creator else headline
        if not ask:
            twitter = f"{twitter} 😭"
        else:
            twitter = f"{twitter}. You buying it?"
        ig = f"{headline}\n\n{creator + ' cooked.' if creator else 'Yeah.'}"
        reddit_title = (f"{creator}: {headline}" if creator else headline)[:80]
        reddit_body = headline
    else:
        twitter = f"{headline} 👀"
        ig = f"{headline}\n\nThat's the news."
        reddit_title = headline[:80]
        reddit_body = headline
    comment = f"Watch 👉 {video}" if video else ""
    if story.get("lane") == "community":
        thread = [
            twitter[:180],
            ("That's the clip. " + headline)[:180],
            "You buying it or scrolling?"[:180],
        ]
        poll_q = "You buying this one?"
        poll_opts = ["Yes", "No", "Already tried", "Hard pass"]
    else:
        thread = [
            twitter[:180],
            "That's the news. That's the tweet.",
            "Right call or safe pick?",
        ]
        poll_q = "Right call?"
        poll_opts = ["Yes", "No", "Too soon", "Who cares"]
    return {
        "twitter": twitter,
        "twitter_thread": thread,
        "poll_question": poll_q,
        "poll_options": poll_opts,
        "instagram": ig,
        "reddit_title": reddit_title,
        "reddit_body": reddit_body,
        "ig_first_comment": comment,
        "title": reddit_title,
    }


def _trim_tweet(text: str, limit: int = 240) -> str:
    t = re.sub(r"\s*https?://\S+", "", (text or "")).strip()
    t = re.sub(r"\s+", " ", t)
    if twitter_len(t) <= limit:
        return t
    while t and twitter_len(t) > limit - 1:
        t = t[:-1]
    return t.rstrip() + "…"


def _clean_poll_options(raw) -> list[str]:
    opts: list[str] = []
    if isinstance(raw, str):
        raw = [x.strip() for x in re.split(r"[,\n|/]+", raw) if x.strip()]
    if not isinstance(raw, list):
        return []
    for item in raw:
        if isinstance(item, dict):
            item = item.get("text") or item.get("label") or item.get("option") or ""
        s = re.sub(r"\s+", " ", str(item or "")).strip()
        if not s:
            continue
        if len(s) > 25:
            s = s[:25].rstrip()
        if s.lower() not in {o.lower() for o in opts}:
            opts.append(s)
        if len(opts) == 4:
            break
    return opts if len(opts) >= 2 else []


def write_copy(
    story: dict,
    photo_credit: str = "",
    angle: int = 0,
    angles_total: int = 1,
    recent_takes: list[str] | None = None,
) -> dict:
    video = story.get("video_url") or ""
    article = story.get("article_url") or ""
    ask = random.random() < 0.34
    user = (
        f"Lane: {story.get('lane')}\n"
        f"Headline (do not restate): {story.get('headline')}\n"
        f"Creator: {story.get('creator') or story.get('video_channel') or ''}\n"
        f"Official video: {video}\n"
        f"Article: {article}\n"
        f"Is official short: {story.get('is_short')}\n"
        f"Excerpt: {(story.get('excerpt') or '')[:280]}\n"
    )
    if ask:
        user += "This post MUST end with one specific question golfers will argue about.\n"
    else:
        user += "No question this time. Land the take and stop.\n"
    if angles_total > 1:
        user += (
            f"This is post {angle + 1} of {angles_total} about the SAME clip. "
            "Different angle each time — don't repeat a previous take.\n"
        )
    recent = [t for t in (recent_takes or []) if t][-8:]
    if recent:
        user += "Do not repeat these recent takes:\n"
        for t in recent:
            user += f"- {t.replace(chr(10), ' ')[:160]}\n"

    parsed = _parse_json(_chat(user) or "")
    base = fallback(story, ask=ask)
    if parsed:
        for k in ("twitter", "instagram", "reddit_title", "reddit_body", "ig_first_comment", "poll_question"):
            if parsed.get(k):
                base[k] = str(parsed[k]).strip()
        if parsed.get("reddit_title"):
            base["title"] = str(parsed["reddit_title"]).strip()[:80]
        th = parsed.get("twitter_thread")
        if isinstance(th, list) and len(th) >= 2:
            base["twitter_thread"] = [str(x).strip() for x in th if str(x).strip()][:4]
        opts = _clean_poll_options(parsed.get("poll_options"))
        if opts:
            base["poll_options"] = opts

    # X unfurls the official clip only if the URL is in the tweet and we attach
    # no other media. Strip a URL the model snuck in, then pin ours once.
    tw = re.sub(r"\s*https?://\S+", "", base["twitter"].strip()).strip()
    # The official URL has to live in the tweet. Native quoteTweetId is dropped
    # by X and we get caption-only. Status URLs unfurl as the real video card.
    if video:
        if twitter_len(tw) > 220:
            tw = _trim_tweet(tw, 220)
        combined = f"{tw}\n\n{video}"
        if twitter_len(combined) > 280:
            combined = f"{_trim_tweet(tw, 180)}\n\n{video}"
        tw = combined
    elif twitter_len(tw) > 240:
        tw = _trim_tweet(tw, 240)
    base["twitter"] = tw
    thread = [
        _trim_tweet(re.sub(r"\s*https?://\S+", "", t))
        for t in (base.get("twitter_thread") or [])
        if str(t).strip()
    ]
    if len(thread) < 2:
        hook = _trim_tweet(re.sub(r"\s*https?://\S+", "", tw)) or "Golf being golf."
        thread = [hook, "That's the clip.", "You buying it?"]
    if video:
        t0 = _trim_tweet(thread[0], 220)
        if video not in t0:
            t0 = f"{t0}\n\n{video}"
            if twitter_len(t0) > 280:
                t0 = f"{_trim_tweet(thread[0], 180)}\n\n{video}"
        thread[0] = t0
    base["twitter_thread"] = thread[:4]
    pq = _trim_tweet(base.get("poll_question") or "You buying this?", 180)
    base["poll_question"] = pq
    opts = _clean_poll_options(base.get("poll_options"))
    if not opts:
        opts = ["Yes", "No", "Maybe", "Who cares"]
    base["poll_options"] = opts
    body = (base.get("reddit_body") or base.get("title") or "").strip()
    body = re.sub(r"\s*https?://\S+", "", body).strip()
    if video:
        body = f"{body}\n\n{video}"
    base["reddit_body"] = body
    comment_bits = []
    existing = (base.get("ig_first_comment") or "").strip()
    if existing and not existing.lower().startswith("watch"):
        # Model sometimes recaps here. Keep only link-like lines.
        keep = [
            ln
            for ln in existing.splitlines()
            if "http" in ln.lower() or ln.lower().startswith("watch") or ln.lower().startswith("read")
        ]
        existing = "\n".join(keep).strip()
    if existing:
        comment_bits.append(existing)
    if video and video not in existing:
        comment_bits.append(f"Watch 👉 {video}")
    if photo_credit and photo_credit not in existing:
        comment_bits.append(photo_credit)
    base["ig_first_comment"] = "\n\n".join(comment_bits)
    base["instagram_first_comment"] = base["ig_first_comment"]
    ig_cap = base.get("instagram") or ""
    if photo_credit:
        ig_cap = ig_cap.replace(photo_credit, "")
    ig_cap = "\n".join(
        ln for ln in ig_cap.splitlines() if not ln.lower().startswith("photo:")
    ).strip()
    base["instagram"] = ig_cap
    base["reddit"] = base.get("reddit_body") or base["title"]
    base["title"] = (base.get("title") or base.get("reddit_title") or story.get("headline") or "golf")[:80]
    base["twitter_chars"] = twitter_len(base["twitter"])

    banned = ("apps.apple.com", "unlock", "subscription", "download eagleeye")
    blob = f"{base['twitter']}\n{base['instagram']}\n{base['reddit']}".lower()
    if story.get("lane") != "eagleeye" and any(b in blob for b in banned):
        print("  copy     model mentioned product — using fallback take")
        base = fallback(story, ask=ask)
        tw = re.sub(r"\s*https?://\S+", "", base["twitter"].strip()).strip()
        if video:
            tw = f"{tw}\n\n{video}"
        base["twitter"] = tw
        body = re.sub(r"\s*https?://\S+", "", (base.get("reddit_body") or base.get("title") or "").strip()).strip()
        if video:
            body = f"{body}\n\n{video}"
        base["reddit"] = body
        base["reddit_body"] = body
        comment_bits = []
        if video:
            comment_bits.append(f"Watch 👉 {video}")
        if photo_credit:
            comment_bits.append(photo_credit)
        base["ig_first_comment"] = "\n\n".join(comment_bits)
        base["instagram_first_comment"] = base["ig_first_comment"]
        base["twitter_chars"] = twitter_len(base["twitter"])
    return base
