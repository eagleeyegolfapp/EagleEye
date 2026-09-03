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

Goal: replies, quote-tweets, profile taps, saves. You are in the group chat, not a recap bot.

This account has RANGE. Do not write every post in the same voice or the same shape.
Pick ONE mode from the user prompt and commit to it:

Modes:
- hot_take: a verdict. You already decided. No question.
- joke: PG-13 golf humor. Specific, not "golf is hard lol". No cussing (no f-words, s-words, a-holes). Hell, damn, crap, sucks, mid, cooked, criminal are fine.
- question: ONE specific fight golfers will answer. Never "thoughts?" or "agree?".
- story: 2-3 short lines that set a scene then punch.
- list: 3 tight beats. Numbers or dashes.
- one_liner: one sentence. Stop.
- roast: credit the creator by name in the sentence and needle them. Affectionate mean.
- praise: rare. When it's actually sick, say so plainly.

Rules:
- Be explicit. If the take is "the captains played it safe," write that. Do not get cute and vague.
- Do NOT restate the video/article title. React to it.
- Do NOT start with "X really posted this" or "That's the news" or "That's the clip." Those are banned openers.
- Do NOT copy a recent take the user lists. Change the angle and the wording.
- Emojis: 0-5, only if they land (👀 😭 🔥 💀 😅 🫡 🧢 📉 📈). No hashtag soup. No emoji at the start of every line.
- Never write "link in comments", "full video below", or "link in bio".
- Do not put URLs in twitter, twitter_thread, instagram, or poll text. The system appends the official URL.
- Never mention EagleEye, App Store, unlock, subscription, ads, or download.
- Never pretend we filmed it or collab'd.
- X tweet (twitter): under 200 characters. No URL. Must make sense if you only read that one line.
- X thread: exactly 3 tweets, each under 200, no URLs. Different jobs: hook / why / button. Do not repeat the hook three times.
- X poll: poll_question under 180. poll_options 3 or 4 answers, EACH 25 chars max, punchy, no emoji.
- Instagram caption: 2-5 short lines. The photo already has overlay_hook on it, so caption is the rest of the take. Line breaks. Can be funnier than X. Do not repeat overlay_hook word for word.
- overlay_hook: 4-8 words ON the photo. Magazine cover line. No source name. No URL. No emoji.
- overlay_question: under 60 chars. Empty if this post has no question.
- Reddit title: debate hook, under 80 chars.
- Reddit body: 1-2 sentences. No URL.
- ig_first_comment: ONLY Watch/Read links.

Return JSON only with keys: twitter, twitter_thread, poll_question, poll_options, instagram, overlay_hook, overlay_question, reddit_title, reddit_body, ig_first_comment, mode."""


def _chat(prompt: str) -> str | None:
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        return None
    model = os.environ.get("XAI_TEXT_MODEL", "grok-4")
    body = {
        "model": model,
        "temperature": 1.05,
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


_FALLBACK_TAKES = [
    ("The safe play aged in dog years.", "hot_take"),
    ("This is the clip you send the group chat at 9:41 pm.", "joke"),
    ("I believed it for exactly one swing.", "one_liner"),
    ("Pretty. Also, completely unhelpful if you actually have to hit the shot.", "roast"),
    ("If this is the standard now, most of us are playing a different sport.", "hot_take"),
    ("Not mad. Just taking notes for the next time someone says 'it's easy'.", "joke"),
    ("The room got quiet for a reason.", "story"),
]


def fallback(story: dict, ask: bool = False) -> dict:
    video = story.get("video_url") or story.get("article_url") or ""
    headline = (story.get("headline") or "golf being golf").rstrip(".")
    creator = story.get("creator") or story.get("video_channel") or ""
    take, mode = random.choice(_FALLBACK_TAKES)
    who = creator.split()[0] if creator else "They"
    if story.get("lane") == "community":
        twitter = f"{who} cooked and I'm not sure it was on purpose. {take}"
        if ask:
            twitter = f"{take} {who} posted it. You buying the lesson or the thumbnail?"
        ig = f"{take}\n\n{who} put this on the internet like we wouldn't notice."
        reddit_title = (f"{who} really went there" if creator else take)[:80]
        reddit_body = take
    else:
        twitter = take if not ask else f"{take} Right call or just the loud one?"
        ig = f"{take}\n\nThat's the whole story. The rest is noise."
        reddit_title = take[:80]
        reddit_body = headline
    comment = f"Watch 👉 {video}" if video else ""
    if story.get("lane") == "community":
        thread = [
            twitter[:180],
            take[:180],
            ("Would you actually try this, or just screenshot it?" if ask else "I'm taking the under.")[:180],
        ]
        poll_q = "You buying this one?"
        poll_opts = ["Buy it", "Hard pass", "Already tried", "Need a mulligan"]
    else:
        thread = [
            twitter[:180],
            take[:180],
            ("Right call or just the safe one?" if ask else "Write it down. This ages fast.")[:180],
        ]
        poll_q = "Right call?"
        poll_opts = ["Right call", "Safe pick", "Too soon", "Who cares"]
    hook_src = re.sub(r"https?://\S+", "", twitter)
    hook_src = re.sub(r"\s+", " ", hook_src).strip()
    overlay_hook = " ".join(hook_src.split()[:7]).rstrip(".!,") or headline[:48]
    overlay_q = poll_q if ask else ""
    return {
        "twitter": twitter,
        "twitter_thread": thread,
        "poll_question": poll_q,
        "poll_options": poll_opts,
        "instagram": ig,
        "overlay_hook": overlay_hook,
        "overlay_question": overlay_q,
        "reddit_title": reddit_title,
        "reddit_body": reddit_body,
        "ig_first_comment": comment,
        "title": reddit_title,
        "mode": mode,
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
    modes = ["hot_take", "joke", "question", "story", "list", "one_liner", "roast", "praise"]
    # Don't let question dominate; keep it in the mix.
    mode = random.choices(modes, weights=[18, 16, 16, 12, 10, 12, 12, 4], k=1)[0]
    ask = mode == "question" or (mode in {"roast", "joke"} and random.random() < 0.25)
    user = (
        f"Lane: {story.get('lane')}\n"
        f"MODE for this post (commit to it): {mode}\n"
        f"Headline (do not restate): {story.get('headline')}\n"
        f"Creator: {story.get('creator') or story.get('video_channel') or ''}\n"
        f"Official video: {video}\n"
        f"Article: {article}\n"
        f"Is official short: {story.get('is_short')}\n"
        f"Excerpt: {(story.get('excerpt') or '')[:280]}\n"
    )
    if ask or mode == "question":
        user += "End with one specific question golfers will argue about. Not 'thoughts?'.\n"
    else:
        user += "No question. Land the take and stop. A verdict, a joke, or a one-liner.\n"
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
        for k in (
            "twitter",
            "instagram",
            "reddit_title",
            "reddit_body",
            "ig_first_comment",
            "poll_question",
            "overlay_hook",
            "overlay_question",
            "mode",
        ):
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
    hook = re.sub(r"https?://\S+", "", (base.get("overlay_hook") or "")).strip()
    hook = re.sub(r"\s+", " ", hook)
    if not hook:
        hook = re.sub(r"https?://\S+", "", ig_cap or base.get("twitter") or "").strip()
        hook = re.sub(r"\s+", " ", hook)
        hook = " ".join(hook.split()[:7]).rstrip(".!,")
    if len(hook.split()) > 8:
        hook = " ".join(hook.split()[:8])
    if len(hook) > 52:
        hook = hook[:50].rsplit(" ", 1)[0]
    base["overlay_hook"] = hook
    oq = re.sub(r"https?://\S+", "", (base.get("overlay_question") or "")).strip()
    oq = re.sub(r"\s+", " ", oq)
    if len(oq) > 64:
        oq = oq[:61].rsplit(" ", 1)[0].rstrip("?.,") + "?"
    base["overlay_question"] = oq
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
