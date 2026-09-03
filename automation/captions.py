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

SYSTEM = """You write captions for a golf account. A person who does not follow golf must still understand every word.

Goal: they know WHAT happened, WHO it is, and WHY it's funny — in that order. Then they reply.

Clarity first. Humor second. Never mystery.

Pick ONE mode and commit:
- hot_take: a verdict. You already decided.
- joke: PG-13 golf humor. Specific. No cussing (no f-words, s-words, a-holes). Hell, damn, crap, sucks, mid, cooked are fine.
- question: ONE concrete question with two real sides. Never "thoughts?" or "agree?".
- story: 2-3 short lines. Fact, then punch.
- one_liner: one sentence. Stop.

Every caption MUST:
1. Name the person or event in plain English on the first line. Not "he". Not "the captains". "Scottie Scheffler" / "the Presidents Cup (USA vs the rest of the world)".
2. Say what actually happened in words a casual fan gets. If you use a golf term (handicap, bunker, pin, FedEx Cup), add a 3-6 word gloss or skip the term.
3. Then the joke or take. Emojis are the norm: 1-3 per post (👀 😭 🔥 😅 🫡 ⛳ 💀 🧢). Not on every line. No hashtag soup.

Banned:
- Cute-vague lines ("the room got quiet", "aged in dog years", "that's the clip") with no fact attached.
- Restating the video title word for word.
- "X really posted this" / "That's the news".
- Pretending we filmed it. EagleEye / App Store / download / subscription.
- URLs (the system adds the official link).
- "link in bio" / "full video below".

X tweet (twitter): under 200 characters. No URL. First clause is who+what. Must make sense alone.
X thread: exactly 3 tweets, each under 200, no URLs. Tweet 1 = who+what. Tweet 2 = the joke. Tweet 3 = the button.
X poll: poll_question under 180, names the topic. poll_options 3 or 4 answers, EACH 25 chars max. Punchy. Emoji ok on question, not on options.
Instagram caption: 2-5 short lines. Line 1 = who+what in plain English. Then the joke. Emojis welcome. Do not repeat overlay_hook word for word.
overlay_hook: 4-8 PLAIN words on the image. Like a TV lower-third. "SCOTTIE RAN THE TABLE" not poetry. No URL. No emoji.
overlay_question: under 60 chars. Empty if no question.
meme_top: 2-6 words. Classic meme setup. ALL CAPS energy. Must be a joke, not a news recap.
meme_bottom: 2-8 words. The punchline. Different from meme_top. Must fit a bar. Funny.
Reddit title: who+what, under 80 chars. A stranger could read it.
Reddit body: 1-2 sentences, same clarity. No URL.
ig_first_comment: ONLY Watch/Read links.

Return JSON only with keys: twitter, twitter_thread, poll_question, poll_options, instagram, overlay_hook, overlay_question, meme_top, meme_bottom, reddit_title, reddit_body, ig_first_comment, mode."""


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
        with urllib.request.urlopen(req, timeout=22, context=CTX) as resp:
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
    ("{who} just posted this and I am not okay 😭", "joke"),
    ("{who} made this look easy. It is not easy 😅", "joke"),
    ("{who} did the thing most of us only do in the group chat 🔥", "hot_take"),
    ("Okay {who}… that one was actually sick 🫡", "one_liner"),
]


def fallback(story: dict, ask: bool = False) -> dict:
    video = story.get("video_url") or story.get("article_url") or ""
    headline = (story.get("headline") or "something happened in golf").rstrip(".")
    creator = story.get("creator") or story.get("video_channel") or ""
    who = creator.split()[0] if creator else "Golf"
    take, mode = random.choice(_FALLBACK_TAKES)
    take = take.format(who=who)
    fact = headline[:110]
    twitter = f"{fact} {take}"
    if ask:
        twitter = f"{fact} You buying this, or is it just a good thumbnail?"
    ig = f"{fact}\n\n{take}"
    reddit_title = fact[:80]
    reddit_body = f"{fact} {take}"
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
        "meme_top": "GOLF BEING GOLF",
        "meme_bottom": "AND WE KEEP COMING BACK",
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
    modes = ["hot_take", "joke", "question", "story", "one_liner"]
    mode = random.choices(modes, weights=[20, 28, 16, 18, 18], k=1)[0]
    ask = mode == "question" or (mode == "joke" and random.random() < 0.2)
    user = (
        f"Lane: {story.get('lane')}\n"
        f"MODE for this post (commit to it): {mode}\n"
        f"What happened (name names, explain it): {story.get('headline')}\n"
        f"Who posted it: {story.get('creator') or story.get('video_channel') or ''}\n"
        f"Official video: {video}\n"
        f"Article: {article}\n"
        f"Is official short: {story.get('is_short')}\n"
        f"Excerpt: {(story.get('excerpt') or '')[:280]}\n"
        "Write for someone who does not follow golf. First line = who + what. Then the joke. Use 1-3 emojis.\n"
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

    print("  copy     writing take…")
    parsed = _parse_json(_chat(user) or "")
    print("  copy     ", (parsed.get("mode") if parsed else "fallback"))
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
            "meme_top",
            "meme_bottom",
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
    def _meme_clip(raw: str, n: int) -> str:
        s = re.sub(r"https?://\S+", "", raw or "")
        s = re.sub(r"\s+", " ", s).strip(" \"'")
        words = s.split()
        return " ".join(words[:n]) if len(words) > n else s
    mt = _meme_clip(base.get("meme_top") or hook, 6)
    mb = _meme_clip(base.get("meme_bottom") or oq or hook, 8)
    if not mt:
        mt = "GOLF BEING GOLF"
    if not mb or mb.lower() == mt.lower():
        mb = "AND WE KEEP COMING BACK"
    base["meme_top"] = mt
    base["meme_bottom"] = mb
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


BROLL_SYSTEM = """You write captions for cinematic golf-course B-roll.

This is NOT news. There is no player, no tournament, no clip to recap.
The video is a drone over a golf course. The caption is about the GAME of golf.

Goal: people who play stop scrolling. Replies, quote-tweets, saves.

Pick ONE mode and commit:
- hot_take: a verdict about golf as a sport. You already decided.
- joke: PG-13 golf humor. Specific. No cussing (no f-words, s-words, a-holes). Hell, damn, crap, sucks, mid, cooked are fine.
- question: ONE fight golfers will actually answer. Never "thoughts?" or "agree?".
- story: 2-3 short lines that set a scene on a course, then punch.
- one_liner: one sentence. Stop.

Rules:
- Write about golf itself: the first tee, the walk, the lie, the score you won't tell anyone, why people keep coming back, the silence, the 4-footer that wrecks a Saturday.
- Do NOT mention a player, a tour, a tournament, a news story, or a specific famous course by name.
- Do NOT pretend we filmed this. Do not say "we shot this" or "our course".
- Do NOT start with "X really posted this" or "That's the news" or "That's the clip."
- Emojis are the norm: 1-3 (⛳ 👀 😭 🔥 😅 🫡 💀). Not a wall of them. No hashtag soup.
- Never write "link in comments", "full video below", or "link in bio".
- Do not put URLs anywhere. There is no article to watch.
- Never mention EagleEye, App Store, unlock, subscription, ads, or download.
- X tweet (twitter): under 200 characters. No URL. Must stand alone.
- X thread: exactly 3 tweets, each under 200, no URLs.
- X poll: poll_question under 180. poll_options 3 or 4 answers, EACH 25 chars max.
- Instagram caption: 2-5 short lines. The video already has overlay_hook on it. Line breaks. Do not repeat overlay_hook word for word.
- overlay_hook: 4-8 words ON the video. Magazine cover line. No emoji. About the game.
- overlay_question: under 60 chars. Empty if this post has no question.
- Reddit title: debate hook about golf, under 80 chars.
- Reddit body: 1-2 sentences. No URL.
- ig_first_comment: empty string.

Return JSON only with keys: twitter, twitter_thread, poll_question, poll_options, instagram, overlay_hook, overlay_question, reddit_title, reddit_body, ig_first_comment, mode."""


_BROLL_FALLBACKS = [
    (
        "Golf is the only sport where you pay to be embarrassed in front of people you like 😭",
        "Eighteen holes. No clock. Nowhere to hide.",
        "THE COURSE DOESN'T CARE",
        "hot_take",
    ),
    (
        "If you can explain why you keep coming back, you haven't played enough.",
        "You tell yourself it's the walk. It's not the walk.",
        "WHY WE KEEP WALKING",
        "one_liner",
    ),
    (
        "A grown adult whispering at a ball they just paid $4 to lose.",
        "That's not a sport. That's a personality.",
        "WHISPER AT THE BALL",
        "joke",
    ),
    (
        "The first tee doesn't care what you shot last week.",
        "That's the deal. You take it or you stay in the parking lot.",
        "THE FIRST TEE KNOWS",
        "story",
    ),
    (
        "Handicap is a rumor you tell yourself until the first bunker.",
        "The grass is honest. You are not.",
        "THE GRASS IS HONEST",
        "hot_take",
    ),
    (
        "Four hours, one honest version of yourself, and a card you might not keep.",
        "That's golf. Everything else is merch.",
        "ONE HONEST VERSION",
        "story",
    ),
]


def _broll_fallback(ask: bool = False) -> dict:
    tw, ig_rest, hook, mode = random.choice(_BROLL_FALLBACKS)
    ig = f"{tw}\n\n{ig_rest}"
    reddit_title = (hook.title() if len(hook) < 80 else tw)[:80]
    if ask:
        tw = tw.rstrip(".!") + ". What's the lie you tell yourself on the first tee?"
    return {
        "twitter": tw,
        "twitter_thread": [
            tw[:180],
            ig_rest[:180],
            ("What's the shot you still think about?" if ask else "Walk it off.")[:180],
        ],
        "poll_question": "What actually keeps you coming back?",
        "poll_options": ["The walk", "The card", "The people", "Can't explain it"],
        "instagram": ig,
        "overlay_hook": hook,
        "overlay_question": "What's the lie on the first tee?" if ask else "",
        "reddit_title": reddit_title,
        "reddit_body": tw,
        "ig_first_comment": "",
        "title": reddit_title,
        "mode": mode,
    }


def write_broll_copy(story: dict, recent_takes: list[str] | None = None) -> dict:
    """Captions about the game of golf. Never a news restatement."""
    modes = ["hot_take", "joke", "question", "story", "one_liner"]
    mode = random.choices(modes, weights=[22, 20, 18, 22, 18], k=1)[0]
    ask = mode == "question"
    user = (
        f"MODE for this post (commit to it): {mode}\n"
        "The video is cinematic drone B-roll of a golf course. Fairways, greens, water, bunkers.\n"
        "Write about the GAME. Not the footage. Not a player. Not a tournament.\n"
    )
    if ask:
        user += "End with one specific question golfers will argue about. Not 'thoughts?'.\n"
    else:
        user += "No question. Land the take and stop.\n"
    recent = [t for t in (recent_takes or []) if t][-8:]
    if recent:
        user += "Do not repeat these recent takes:\n"
        for t in recent:
            user += f"- {t.replace(chr(10), ' ')[:160]}\n"

    print("  copy     b-roll take about the game…")
    parsed = _parse_json(_chat_broll(user) or "")
    print("  copy     ", (parsed.get("mode") if parsed else "fallback"))
    base = _broll_fallback(ask=ask)
    if parsed:
        for k in (
            "twitter",
            "instagram",
            "reddit_title",
            "reddit_body",
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

    tw = re.sub(r"\s*https?://\S+", "", base["twitter"].strip()).strip()
    if twitter_len(tw) > 240:
        tw = _trim_tweet(tw, 240)
    base["twitter"] = tw
    thread = [
        _trim_tweet(re.sub(r"\s*https?://\S+", "", t))
        for t in (base.get("twitter_thread") or [])
        if str(t).strip()
    ]
    if len(thread) < 2:
        thread = [tw[:180] or "Golf being golf.", "The course doesn't care.", "Walk it off."]
    base["twitter_thread"] = thread[:4]
    pq = _trim_tweet(base.get("poll_question") or "What keeps you coming back?", 180)
    base["poll_question"] = pq
    opts = _clean_poll_options(base.get("poll_options"))
    if not opts:
        opts = ["The walk", "The card", "The people", "Can't explain"]
    base["poll_options"] = opts
    body = (base.get("reddit_body") or base.get("title") or "").strip()
    body = re.sub(r"\s*https?://\S+", "", body).strip()
    base["reddit_body"] = body
    base["reddit"] = body
    base["ig_first_comment"] = ""
    base["instagram_first_comment"] = ""
    ig_cap = re.sub(r"https?://\S+", "", base.get("instagram") or "").strip()
    ig_cap = "\n".join(ln for ln in ig_cap.splitlines() if not ln.lower().startswith("photo:")).strip()
    base["instagram"] = ig_cap
    hook = re.sub(r"https?://\S+", "", (base.get("overlay_hook") or "")).strip()
    hook = re.sub(r"\s+", " ", hook)
    if not hook:
        hook = " ".join(tw.split()[:7]).rstrip(".!,") or "THE COURSE DOESN'T CARE"
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
    base["title"] = (base.get("title") or base.get("reddit_title") or "The game")[:80]
    base["twitter_chars"] = twitter_len(base["twitter"])
    banned = ("apps.apple.com", "unlock", "subscription", "download eagleeye")
    blob = f"{base['twitter']}\n{base['instagram']}\n{base['reddit']}".lower()
    if any(b in blob for b in banned):
        print("  copy     model mentioned product — using b-roll fallback")
        base = _broll_fallback(ask=ask)
        base["twitter_chars"] = twitter_len(base["twitter"])
        base["reddit"] = base.get("reddit_body") or base["title"]
        base["instagram_first_comment"] = ""
    return base


def _chat_broll(prompt: str) -> str | None:
    key = (os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        return None
    model = os.environ.get("XAI_TEXT_MODEL", "grok-4")
    body = {
        "model": model,
        "temperature": 1.05,
        "messages": [
            {"role": "system", "content": BROLL_SYSTEM},
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
        with urllib.request.urlopen(req, timeout=22, context=CTX) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        print(f"  grok b-roll copy failed: {e}")
        return None

