#!/usr/bin/env python3
"""Pick a lane, research, attach media, post to Late, email the report."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from captions import write_copy
from late_client import create_post, persist_ids, resolve_accounts
from mailer import send_report
from find_media import credit_line, find_subject_image
from media import download
from research import active_events, fetch_link_story, research_community, research_news
from story_quality import story_keys
from workflow_one import load_config, twitter_len as _twlen

# In-run dedupe so today's slots don't all pick the same clip before state is saved.
_RUN_USED: set[str] = set()
_RUN_CREATORS: list[str] = []
_RUN_COPY: list[str] = []
_RUN_FLOURISH: list[str] = []
_RUN_LANES: list[str] = []

HERE = Path(__file__).resolve().parent
TZ = ZoneInfo("America/New_York")
STATE = HERE / "state" / "rotation.json"


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"lanes": [], "video_ids": []}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + "\n")


def pick_lane(cfg: dict, override: str | None) -> str:
    if override and override not in {"auto", ""}:
        if override == "golf-world":
            return "news"
        if override == "eagleeye":
            print("  product lane paused until app footage is ready — using news/community")
        else:
            return override
    import random

    mix = cfg.get("mix") or {"news": 40, "community": 60, "eagleeye": 0}
    weights = {
        k: int(v or 0)
        for k, v in mix.items()
        if k in {"news", "community"} and int(v or 0) > 0
    }
    if not weights:
        weights = {"news": 40, "community": 60}
    # Live events tilt news, they do not replace the mix.
    if active_events(cfg):
        weights["news"] = weights.get("news", 0) + 20
    # Don't run the same lane three times in a row.
    last_two = ((load_state().get("lanes") or []) + _RUN_LANES)[-2:]
    if len(last_two) == 2 and last_two[0] == last_two[1] and last_two[0] in weights and len(weights) > 1:
        weights = {k: v for k, v in weights.items() if k != last_two[0]} or weights
    total = sum(weights.values())
    r = random.uniform(0, total)
    acc = 0.0
    for name, w in weights.items():
        acc += w
        if acc >= r:
            return name
    return next(iter(weights))


def automation_ended(cfg: dict) -> bool:
    raw = (cfg.get("ends_on") or "").strip()
    if not raw:
        return False
    try:
        end = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return False
    return datetime.now(TZ).date() > end


def notify_if_ended(cfg: dict) -> bool:
    state = load_state()
    if not automation_ended(cfg):
        if state.get("ended_email_sent"):
            state["ended_email_sent"] = False
            save_state(state)
        return False
    print("STOPPED  campaign end date", cfg.get("ends_on"), "has passed")
    if state.get("ended_email_sent"):
        return True
    to_addr = cfg.get("report_email") or os.environ.get("REPORT_EMAIL") or "eagleeyegolfapp@gmail.com"
    try:
        send_report(
            to_addr,
            "EagleEye social automation has ended",
            (
                f"The end date {cfg.get('ends_on')} has passed.\n\n"
                "No more posts will be scheduled until you set a new end date "
                "in the EagleEye dashboard and save.\n"
            ),
        )
    except Exception as e:  # noqa: BLE001
        print("  end-email failed:", e)
    state["ended_email_sent"] = True
    save_state(state)
    return True


def parse_hhmm(raw: str) -> tuple[int, int]:
    s = (raw or "").strip().upper().replace(".", "")
    ampm = None
    if s.endswith("AM") or s.endswith("PM"):
        ampm = s[-2:]
        s = s[:-2].strip()
    parts = s.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return hour % 24, minute % 60


def slot_times(cfg: dict) -> list[str]:
    slots = cfg.get("slots") or []
    times = []
    for s in slots:
        raw = (s.get("time") if isinstance(s, dict) else str(s)) or ""
        if not raw:
            continue
        h, m = parse_hhmm(raw)
        times.append(f"{h:02d}:{m:02d}")
    if not times:
        h, m = parse_hhmm(cfg.get("post_time") or "09:30")
        times = [f"{h:02d}:{m:02d}"]
    # Keep user order, drop dupes.
    seen, out = set(), []
    for t in times:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def next_occurrence(hhmm: str, now: datetime | None = None) -> datetime:
    """Exact clock time in Eastern: today if still ahead, otherwise tomorrow."""
    now = now or datetime.now(TZ)
    hour, minute = parse_hhmm(hhmm)
    dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Exact clock. Only roll to tomorrow after that minute has already started.
    if dt <= now:
        dt += timedelta(days=1)
    return dt


def slot_preview(cfg: dict) -> list[dict]:
    now = datetime.now(TZ)
    booked = _booked_times()
    out = []
    for t in slot_times(cfg):
        dt = next_occurrence(t, now)
        for _ in range(14):
            key = dt.strftime("%Y-%m-%d %H:%M")
            if key not in booked:
                break
            dt = dt + timedelta(days=1)
        out.append({"time": t, "next": dt.strftime("%Y-%m-%d %H:%M")})
    return out


def _booked_times() -> set[str]:
    booked = set()
    for k, st in (load_state().get("posted_slots") or {}).items():
        if st in {"scheduled", "published", "submitted"}:
            booked.add(k)
    if not (os.environ.get("LATE_API_KEY") or "").strip():
        return booked
    try:
        from late_client import list_posts

        for p in list_posts(status="scheduled", limit=100):
            raw = str(p.get("scheduledFor") or "")
            if not raw:
                continue
            raw = raw.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            booked.add(dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M"))
    except SystemExit:
        return booked
    except Exception as e:  # noqa: BLE001
        print("  late    could not list scheduled:", e)
    return booked


def remaining_slots(cfg: dict, override: str | None, one: bool = False) -> list[str]:
    if override:
        return [override]
    now = datetime.now(TZ)
    booked = _booked_times()
    upcoming: list[datetime] = []
    for t in slot_times(cfg):
        dt = next_occurrence(t, now)
        for _ in range(14):
            key = dt.strftime("%Y-%m-%d %H:%M")
            if key not in booked:
                upcoming.append(dt)
                break
            dt = dt + timedelta(days=1)
    upcoming.sort()
    if not upcoming:
        return []
    if one:
        return [upcoming[0].strftime("%Y-%m-%d %H:%M")]
    today = [dt for dt in upcoming if dt.date() == now.date()]
    chosen = today if today else upcoming[:1]
    return [dt.strftime("%Y-%m-%d %H:%M") for dt in chosen]


def schedule_when(cfg: dict, override: str | None) -> str:
    return remaining_slots(cfg, override, one=True)[0]


DEFAULT_REDDIT_SUBS = [
    "golfcirclejerk",
    "WeekendGolfers",
    "golfswing",
    "PGA_Tour",
    "livgolf",
    "GolfTravel",
    "golf",
]


def weekly_reddit_targets(cfg: dict, state: dict) -> tuple[list[str], dict]:
    """Once per ISO week, also post this slot to one rotating golf subreddit."""
    if not cfg.get("reddit_weekly", True):
        return [], {}
    iso = datetime.now(TZ).strftime("%G-W%V")
    if state.get("reddit_weekly_iso") == iso:
        return [], {}
    raw = cfg.get("reddit_subs") or DEFAULT_REDDIT_SUBS
    profile = (cfg.get("reddit_subreddit") or "u_eagleeyegolfapp").lstrip("r/")
    subs = []
    for s in raw:
        name = str(s or "").strip().lstrip("r/")
        if name and name.lower() != profile.lower() and name not in subs:
            subs.append(name)
    if not subs:
        return [], {}
    idx = int(state.get("reddit_weekly_index") or 0)
    pick = subs[idx % len(subs)]
    print(f"  reddit   weekly extra r/{pick} (once this week)")
    return [pick], {"reddit_weekly_iso": iso, "reddit_weekly_index": idx + 1}


def pick_flourish(cfg: dict, state: dict) -> str:
    """One extra format per slot: thread, story, or poll — never stacked."""
    import random

    mix = cfg.get("flourish") or {"none": 40, "thread": 25, "story": 20, "poll": 15}
    weights = {k: int(v or 0) for k, v in mix.items() if int(v or 0) > 0}
    if not weights:
        weights = {"none": 40, "thread": 25, "story": 20, "poll": 15}
    last = ((state.get("flourishes") or []) + _RUN_FLOURISH)[-1:] 
    if last and last[0] in weights and len(weights) > 1:
        weights = {k: v for k, v in weights.items() if k != last[0]} or weights
    total = sum(weights.values())
    r = random.uniform(0, total)
    acc = 0.0
    for name, w in weights.items():
        acc += w
        if acc >= r:
            return name
    return "none"


def late_payload(
    story: dict,
    copy: dict,
    when: str,
    cfg: dict,
    media: dict,
    extra_reddit: list[str] | None = None,
    flourish: str = "none",
) -> dict:
    mapping = {
        "twitter": os.environ.get("LATE_TWITTER_ACCOUNT_ID", ""),
        "instagram": os.environ.get("LATE_INSTAGRAM_ACCOUNT_ID", ""),
        "reddit": os.environ.get("LATE_REDDIT_ACCOUNT_ID", ""),
    }
    still = media.get("still") or ""
    official = media.get("official") or story.get("video_url") or ""
    has_video = bool(official)
    platforms = []
    for name in cfg.get("platforms_stills") or ["twitter", "instagram", "reddit"]:
        acc = mapping.get(name, "")
        if not acc:
            continue
        # Instagram cannot play a linked YouTube/Vimeo player. It needs a photo.
        # X and Reddit render the embed — never attach a still on top of a video.
        if name == "instagram" and not still:
            print("  skip IG — no rights-safe photo of the subject")
            continue
        if name == "reddit":
            profile = (cfg.get("reddit_subreddit") or "u_eagleeyegolfapp").lstrip("r/")
            targets = [profile]
            for extra in extra_reddit or []:
                sub = str(extra or "").strip().lstrip("r/")
                if sub and sub not in targets:
                    targets.append(sub)
            for sub in targets:
                psd = {
                    "subreddit": sub,
                    "title": (copy.get("title") or copy.get("reddit_title") or "")[:300],
                }
                if official:
                    psd["url"] = official
                label = sub if sub.startswith("u_") else f"r/{sub}"
                print(f"  reddit   {label}")
                platforms.append(
                    {
                        "platform": "reddit",
                        "accountId": acc,
                        "customContent": copy.get("reddit") or copy.get("reddit_body") or "",
                        "platformSpecificData": psd,
                    }
                )
            continue
        item: dict = {
            "platform": name,
            "accountId": acc,
            "customContent": copy.get(name, copy["reddit"]),
        }
        if name == "twitter":
            if flourish == "poll":
                q = (copy.get("poll_question") or copy.get("twitter") or "").strip()
                q = re.sub(r"\s*https?://\S+", "", q).strip()
                opts = [str(o).strip()[:25] for o in (copy.get("poll_options") or []) if str(o).strip()][:4]
                if q and len(opts) >= 2:
                    if _twlen(q) > 250:
                        q = q[:240].rstrip() + "…"
                    item["customContent"] = q
                    item["platformSpecificData"] = {
                        "poll": {"options": opts, "duration_minutes": 1440}
                    }
                    print("  twitter  poll", q[:50], "|", " / ".join(opts))
                else:
                    print("  twitter  poll skipped — using single tweet")
            elif flourish == "thread":
                thread = [t for t in (copy.get("twitter_thread") or []) if t]
                if len(thread) >= 2:
                    items = [{"content": t} for t in thread[:4]]
                    item["platformSpecificData"] = {"threadItems": items}
                    item["customContent"] = items[0]["content"]
                    print("  twitter  thread", len(items), "tweets")
            else:
                print("  twitter  single")
            platforms.append(item)
            continue
        if name == "instagram":
            # Omit contentType for feed — Late only accepts "story" / "reels".
            # "post" is invalid and Instagram ships with no media.
            item["platformSpecificData"] = {
                "firstComment": copy.get("instagram_first_comment")
                or copy.get("ig_first_comment")
                or "",
            }
            item["customMedia"] = [{"url": still, "type": "image"}]
            platforms.append(item)
            if flourish == "story":
                platforms.append(
                    {
                        "platform": "instagram",
                        "accountId": acc,
                        "customContent": "",
                        "platformSpecificData": {"contentType": "story"},
                        "customMedia": [{"url": still, "type": "image"}],
                    }
                )
                print("  instagram feed + story")
            else:
                print("  instagram feed")
            continue
        platforms.append(item)
    if not platforms:
        raise SystemExit("No Late account IDs — connect X, Instagram, Reddit.")
    if not official and not still:
        raise SystemExit("No embed URL and no rights-safe still.")
    payload = {
        "content": copy["reddit"],
        "title": copy["title"],
        "timezone": cfg.get("timezone", "America/New_York"),
        "scheduledFor": when.replace(" ", "T"),
        "publishNow": False,
        "isDraft": False,
        "platforms": platforms,
    }
    # Global mediaItems attach to every network and kill video unfurls.
    # Only set them when there is no video (still-only post) or IG is the sole target.
    if still and not has_video:
        payload["mediaItems"] = [{"url": still, "type": "image"}]
    if os.environ.get("LATE_PROFILE_ID"):
        payload["profileId"] = os.environ["LATE_PROFILE_ID"]
    return payload


FALLBACK_STILL = (
    "https://raw.githubusercontent.com/TheSgambini/eagleeyelabsllc"
    "/main/_late-media/test-golf-world-first-tee.jpg"
)


def host_media(url: str, slug: str, content_type: str = "image/jpeg") -> str:
    """Upload to Late so Instagram can fetch it. Never send Wikimedia/Flickr hotlinks."""
    if "getlate" in url or "zernio.com" in url:
        return url
    from late_client import presign_and_upload

    blob = download(url)
    if len(blob) < 2000:
        raise RuntimeError(f"image too small ({len(blob)} bytes) from {url[:80]}")
    ext = "mp4" if "video" in content_type or url.endswith(".mp4") else "jpg"
    hosted = presign_and_upload(blob, f"{slug}.{ext}", content_type)
    print("  media   uploaded to Late", ext, hosted[:60])
    return hosted


def run_once(
    kind: str | None,
    when: str | None,
    live: bool,
    story_override: dict | None = None,
    angle: int = 0,
    angles_total: int = 1,
) -> dict:
    cfg = load_config()
    if notify_if_ended(cfg):
        return {"status": "ended"}
    if not cfg.get("enabled", True) and story_override is None:
        raise SystemExit("Automation is paused. Open the dashboard and turn it back on.")
    now = datetime.now(TZ)
    if (
        story_override is None
        and now.weekday() not in (cfg.get("days") or list(range(7)))
        and kind in {None, "auto"}
    ):
        print("Today is not a posting day in the dashboard. Skipping.")
        return {"status": "skipped-day"}

    if story_override:
        story = story_override
        lane = story.get("lane") or "community"
        when_s = when or schedule_when(cfg, when)
    else:
        lane = pick_lane(cfg, kind)
        when_s = schedule_when(cfg, when)
        story = None
    state = load_state()
    posted = state.get("posted_slots") or {}
    if live and posted.get(when_s) in {"scheduled", "published", "submitted"}:
        print("SKIP       already have a live post for", when_s)
        return {"status": "already-posted", "when": when_s}
    used_ids = set(state.get("video_ids") or [])
    used_keys = set(state.get("used_keys") or []) | set(used_ids) | set(_RUN_USED)
    used_creators = list(state.get("used_creators") or []) + list(_RUN_CREATORS)

    print(f"LANE       {lane}")
    print(f"WHEN       {when_s} {cfg.get('timezone')}")

    if story is None:
        if lane == "eagleeye":
            print("  product lane paused until app footage is ready")
            lane = pick_lane(cfg, "auto")
            print(f"LANE       {lane} (was product)")

        kwargs = dict(used_ids=used_ids, used_keys=used_keys, used_creators=used_creators)
        if lane == "community":
            try:
                story = research_community(cfg, **kwargs)
            except Exception as e:  # noqa: BLE001
                print(f"  community research failed ({e}); trying news")
                story = research_news(cfg, **kwargs)
                lane = "news"
        else:
            try:
                story = research_news(cfg, **kwargs)
            except Exception as e:  # noqa: BLE001
                print(f"  news research failed ({e}); trying community")
                story = research_community(cfg, **kwargs)
                lane = "community"

    _RUN_USED.update(story_keys(story))
    who = story.get("creator") or story.get("video_channel") or ""
    if who:
        _RUN_CREATORS.append(who)

    extra_reddit: list[str] = []
    weekly_patch: dict = {}
    if story_override is None:
        extra_reddit, weekly_patch = weekly_reddit_targets(cfg, state)
    flourish = pick_flourish(cfg, state)
    _RUN_FLOURISH.append(flourish)
    print(f"FLOURISH   {flourish}  (one extra — not stacked)")

    photo = find_subject_image(story)
    credit = credit_line(photo)
    copy = write_copy(
        story,
        photo_credit=credit,
        angle=angle,
        angles_total=angles_total,
        recent_takes=(state.get("recent_copy") or []) + _RUN_COPY,
    )
    _RUN_COPY.append((copy.get("twitter") or "")[:180])
    still = (photo or {}).get("url") or ""
    official = story.get("video_url") or story.get("article_url") or ""
    if live:
        found = resolve_accounts()
        persist_ids(found)
        hosted = ""
        if still:
            try:
                hosted = host_media(still, story["id"], "image/jpeg")
            except Exception as e:  # noqa: BLE001
                print("  media   primary still failed:", e)
        if not hosted:
            fb = (cfg.get("fallback_still") or FALLBACK_STILL).strip()
            try:
                hosted = host_media(fb, "golf-fallback", "image/jpeg")
            except Exception as e:  # noqa: BLE001
                print("  media   fallback still failed:", e)
        still = hosted
        if not still:
            raise SystemExit("Instagram needs a Late-hosted still. Upload failed.")
    media = {"still": still, "official": official, "photo": photo or {}}
    if not official and not still:
        raise SystemExit("No official embed and no rights-safe photo of the subject.")

    if story.get("is_short"):
        kind_used = "official-short"
    elif official and ("youtube" in official or "vimeo" in official or "x.com" in official):
        kind_used = "official-video"
    elif official:
        kind_used = "official-link"
    else:
        kind_used = "cc-photo"
    print("HEADLINE  ", story["headline"])
    print("EMBED     ", official or "(none)", "short=" + str(bool(story.get("is_short"))))
    print("IG PHOTO  ", still or "(skipped — no CC/PD match)")
    print("PACKAGED  ", kind_used)
    print("X CHARS   ", copy["twitter_chars"])
    print("X COPY    ", copy["twitter"].replace("\n", " / "))
    th = copy.get("twitter_thread") or []
    if th:
        print("THREAD    ", " || ".join(t.replace("\n", " ")[:60] for t in th))
    if copy.get("poll_question"):
        print("POLL      ", copy["poll_question"], "|", " / ".join(copy.get("poll_options") or []))

    result = {
        "lane": lane,
        "when": when_s,
        "headline": story["headline"],
        "video_url": official,
        "still": still,
        "photo_credit": credit,
        "packaged": kind_used,
        "flourish": flourish,
        "copy": copy["twitter"],
        "late_id": "",
        "status": "dry-run",
    }
    if live:
        payload = late_payload(
            story, copy, when_s, cfg, media, extra_reddit=extra_reddit, flourish=flourish
        )
        idem = f"eagleeye-{story['id']}-{when_s.replace(' ', 'T')}"
        res = create_post(payload, idempotency_key=idem)
        post = res.get("post") or res.get("existingPost") or res
        late_id = str(post.get("_id") or post.get("id") or "")
        status = str(post.get("status") or "submitted")
        result["late_id"] = late_id
        result["status"] = status
        print("LATE       ", late_id, status)
        result["flourish"] = flourish
        to_addr = cfg.get("report_email") or os.environ.get("REPORT_EMAIL") or "eagleeyegolfapp@gmail.com"
        body = (
            f"EagleEye Golf App — post scheduled\n\n"
            f"When:      {when_s} America/New_York\n"
            f"Lane:      {lane}\n"
            f"Flourish:  {flourish}\n"
            f"Headline:  {story['headline']}\n"
            f"Video:     {story.get('video_url') or '(image only)'}\n"
            f"Still:     {still}\n"
            f"Formats:   core + {flourish}\n"
            f"Late id:   {late_id}\n"
            f"Status:    {status}\n\n"
            f"Caption:\n{copy['twitter']}\n"
        )
        try:
            send_report(to_addr, f"EagleEye posted: {story['headline'][:60]}", body)
        except Exception as e:  # noqa: BLE001
            print("  email   failed:", e)
    else:
        print("LATE       dry-run")
        print("FORMATS    core +", flourish)

    _RUN_LANES.append(lane)
    keys = story_keys(story)
    yids = [k for k in keys if not k.startswith("fp:") and not k.startswith("youtube:") and "://" not in k]
    if live and result.get("status") in {"scheduled", "published", "submitted"}:
        posted[when_s] = result["status"]
        state["posted_slots"] = dict(list(posted.items())[-80:])
        prev_keys = list(state.get("used_keys") or [])
        state["used_keys"] = list(dict.fromkeys(prev_keys + keys))[-200:]
        prev_vids = list(state.get("video_ids") or [])
        state["video_ids"] = list(dict.fromkeys(prev_vids + yids))[-200:]
        if who:
            state["used_creators"] = (list(state.get("used_creators") or []) + [who])[-20:]
        state["recent_copy"] = (list(state.get("recent_copy") or []) + [(copy.get("twitter") or "")[:180]])[-12:]
        state["lanes"] = (state.get("lanes") or [])[-20:] + [lane]
        state["flourishes"] = (list(state.get("flourishes") or []) + [flourish])[-20:]
        state["last"] = result
        if weekly_patch:
            state.update(weekly_patch)
    else:
        state["lanes"] = (state.get("lanes") or [])[-20:] + [lane]
        state["last"] = result
    save_state(state)
    log = HERE / "logs" / "posts.csv"
    log.parent.mkdir(parents=True, exist_ok=True)
    line = ",".join(
        [
            datetime.now(TZ).isoformat(timespec="seconds"),
            lane,
            story.get("id", ""),
            when_s,
            '"' + copy["twitter"].replace('"', "'").replace("\n", " ") + '"',
            still,
            story.get("video_url") or "",
            result.get("late_id") or "",
            result.get("status") or "",
        ]
    )
    if not log.exists():
        log.write_text("ts,kind,bank_id,schedule_time,copy,media_url,video_url,late_id,status\n")
    with log.open("a") as f:
        f.write(line + "\n")
    return result


def run_spotlight(url: str, count: int, every_hours: float, live: bool) -> list[dict]:
    """Schedule N posts about one pasted link, off the daily cadence."""
    cfg = load_config()
    if notify_if_ended(cfg):
        return [{"status": "ended"}]
    count = max(1, min(int(count), 8))
    every_hours = max(2.0, min(float(every_hours), 48.0))
    story = fetch_link_story(url, cfg)
    print("SPOTLIGHT ", story.get("headline"), story.get("video_url"))
    now = datetime.now(TZ)
    start = now.replace(second=0, microsecond=0) + timedelta(minutes=3)
    ends = None
    if (cfg.get("ends_on") or "").strip():
        try:
            ends = datetime.strptime(cfg["ends_on"], "%Y-%m-%d").replace(tzinfo=TZ)
            ends = ends.replace(hour=23, minute=59)
        except ValueError:
            ends = None
    out: list[dict] = []
    state = load_state()
    posted = state.get("posted_slots") or {}
    for i in range(count):
        dt = start + timedelta(hours=every_hours * i)
        # Nudge off any time already booked.
        while posted.get(dt.strftime("%Y-%m-%d %H:%M")) in {"scheduled", "published", "submitted"}:
            dt += timedelta(minutes=15)
        if ends and dt > ends:
            print("SPOTLIGHT stop — would pass campaign end date")
            break
        when_s = dt.strftime("%Y-%m-%d %H:%M")
        one = dict(story)
        one["id"] = f"{story['id']}-a{i+1}"
        res = run_once(
            "community",
            when_s,
            live,
            story_override=one,
            angle=i,
            angles_total=count,
        )
        out.append(res)
        posted = load_state().get("posted_slots") or posted
    return out
