"""Clip queue, AI approval, spaced-out posting, disk cleanup.

Each clip lives in output/queue/<id>/ as v1/v2/v3.mp4 (one per hook) + meta.json.
status: pending -> approved | rejected -> posted

With [auto] enabled, Gemini WATCHES each clip and approves or rejects it. Approved
clips are posted one at a time, spaced out, within each platform's daily cap.
If Gemini can't review a clip, it is never auto-posted.
"""
from __future__ import annotations

import json
import re
import logging
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from . import llm, notify
from .config import ROOT

log = logging.getLogger(__name__)
QUEUE = ROOT / "output" / "queue"
HISTORY = ROOT / "output" / "upload_history.json"


def save(meta: dict) -> None:
    d = QUEUE / meta["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, indent=2))


def load(clip_id: str) -> dict:
    return json.loads((QUEUE / clip_id / "meta.json").read_text())


def items(status: str | None = None) -> list[dict]:
    out = []
    for p in sorted(QUEUE.glob("*/meta.json")):
        try:
            m = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if status is None or m["status"] == status:
            out.append(m)
    return out


# ---- AI review --------------------------------------------------------------
REVIEW_PROMPT = """You are the final quality check before this vertical GTA 6 clip is posted to
YouTube Shorts / TikTok / Reels on a clipping channel. Watch the whole video.

Reject (approve=false) if ANY of these: a dead opening (in the first 2 seconds nothing is said, nothing
moves and nobody reacts - most viewers swipe away right there), loading/menu/pause/map screens most of the time, an ad break
or "commercial break" slate, black or frozen video, nothing really happens, it cuts off mid-action
before the payoff, captions badly wrong, hateful content, explicit sexual content (nudity, sex acts,
strip-club or lap-dance scenes), anyone who looks under 18 shown in a sexual way, a clip that is mainly
the camera lingering on the body of a real person who is not part of the stream, slurs, real personal
info on screen
(addresses, phone numbers, donation alerts with full names), or EVERY hook promises something that
does not happen in the clip.

Suggestive content is WANTED, not a reason to reject: flirting, romance, kissing, attractive game
characters, bikinis, beach / pool / club scenes, and the streamer's reaction to them.

Title: TITLE
The title and hooks were written from the transcript alone, so they are sometimes wrong about what is
on screen. A wrong TITLE is not a reason to reject a good clip: put an accurate replacement in
"new_title" (under 70 characters, curiosity-first, names the streamer, no spoiler, at most 1 emoji, and
it must say GTA 6 only if this really is GTA 6). If the title is already accurate, "new_title": "".

GAMEPLAY RULE: gameplay = GTA 6 game footage is clearly visible on screen (the game world, the
player's character or vehicle, the HUD) for MOST of the clip, and the key moment happens IN the game.
A small facecam over the game is fine. It is NOT gameplay if the streamer is just talking to the camera,
sitting/lying in their room, reading chat, reacting to other videos, watching trailers, or talking
ABOUT GTA 6 without playing it - even if the topic is GTA 6. Set "gameplay" honestly.
Also set "gta_related": true only if the clip is clearly about GTA 6 (playing it, or the streamer
talking about / reacting to GTA 6 specifically). Other games or random chatting = false.
Set "is_gta6": false if the game on screen is a different game (GTA 5 / GTA Online / FiveM roleplay,
Red Dead, Call of Duty, anything that is not GTA 6); true only when it really is GTA 6.
Set "trailer_reaction": true if the clip mostly shows an official trailer or someone else's video
(the streamer watching/reacting to it) rather than their own stream.
Set "kind" to the best fit: "gameplay"; "music_reaction" (the streamer reacting to GTA 6 music, the radio
or soundtrack, or a song about GTA 6); "culture" (a GTA 6 cultural reference: real-world people, brands,
memes, Miami / Vice City culture, parodies, things the game is referencing); "reaction" (reacting to
something else about GTA 6); "talk" (opinions, theories, stories about GTA 6); or "other".

THEMES_LINE
Hooks (the white banner text; the video shows hook 1, the others are alternatives):
HOOKS

best_hook = among the hooks that are TRUE to what happens, the one that makes a scroller most curious
without spoiling the payoff.

Return JSON: {"approve": bool, "gameplay": bool, "is_gta6": bool, "gta_related": bool, "trailer_reaction": bool, "kind": str, "score": 1-10 (how likely a stranger watches to the end),
"theme": bool, "new_title": str, "best_hook": 1-3, "thumbnail_second": number (the most eye-catching moment, e.g. a big reaction or
crash, in seconds from the start), "problems": [short strings], "reason": "one sentence"}"""


REVIEW_PROMPT_ANY = """You are the final quality check before this vertical clip of a big streamer is posted
to YouTube Shorts on a clipping channel. This clip is NOT from a GTA stream; it is only wanted if it has
real viral potential. Watch the whole video.

Reject (approve=false) if ANY of these: a dead opening (nothing said, moving or reacting in the first
2 seconds), nothing really happens, ordinary chatting or reading chat, an ad
break, black or frozen video, it cuts off before the payoff, captions badly wrong, hateful content,
explicit sexual content (nudity, sex acts; flirting, romance, bikinis and suggestive jokes are fine),
anyone who looks under 18 shown in a sexual way, a clip that is mainly the camera lingering on the body
of a real person who is not part of the stream, slurs, real personal info on screen, the streamer's face is not visible, or EVERY hook
promises something that does not happen.

Title: TITLE
The title and hooks were written from the transcript alone. A wrong TITLE is not a reason to reject a
good clip: put an accurate replacement in "new_title" (under 70 characters, curiosity-first, names the
streamer, no spoiler, no GTA wording). If the title is already accurate, "new_title": "".

Set "kind": "music_reaction" (reacting to a song, an artist, dancing or singing along - note the country
or culture if it is foreign to the streamer), "culture" (food, language, traditions, meeting people
abroad), "romance" (dating, rizz and flirting, couples, love, relationship or therapy-style talk),
"reaction" (a big genuine reaction to something else), "talk", or "other".
Set "music_plays": true if a commercial song is clearly audible for most of the clip.

THEMES_LINE
Hooks (the white banner text; the video shows hook 1, the others are alternatives):
HOOKS

best_hook = among the hooks that are TRUE to what happens, the one that makes a scroller most curious
without spoiling the payoff.

Return JSON: {"approve": bool, "kind": str, "music_plays": bool, "score": 1-10 (how likely a stranger
watches to the end and shares it), "theme": bool, "new_title": str, "best_hook": 1-3, "thumbnail_second": number, "problems": [short
strings], "reason": "one sentence"}"""


def _themes_line(cfg: dict) -> str:
    themes = cfg["auto"].get("themes") or []
    if not themes:
        return 'Set "theme": false.'
    return ('Set "theme": true if the clip is mainly about one of the channel\'s priority themes ('
            + ", ".join(themes) + "): flirting or rizzing someone, a date, a love or romance scene, a couple "
            "moment, relationship or therapy-style talk, or the streamer reacting to an attractive character, "
            "a bikini / beach / club scene. Otherwise false. If you write a new_title for such a clip keep it "
            "clean and playful: no explicit sexual words or body-part words.")


_OTHER_GAME = re.compile(r"\bGTA ?(5|V|Online|RP)\b|\bFiveM\b|\bRed Dead\b", re.I)


def auto_review(clip_id: str, cfg: dict, src: Path | None = None) -> dict:
    meta = load(clip_id)
    src = QUEUE / clip_id / "v1.mp4"
    with tempfile.TemporaryDirectory() as td:
        proxy = Path(td) / "p.mp4"   # small copy so it fits in one free Gemini request
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                        "-vf", "scale=360:-2,fps=15", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
                        "-c:a", "aac", "-b:a", "48k", "-ac", "1", str(proxy)], check=True)
        hooks = "\n".join(f"{i}. {h['text']}" for i, h in enumerate(meta["hooks"], 1))
        any_topic = meta.get("topic") == "any"
        verdict = llm.watch_video(cfg, proxy.read_bytes(),
                                  (REVIEW_PROMPT_ANY if any_topic else REVIEW_PROMPT)
                                  .replace("THEMES_LINE", _themes_line(cfg))
                                  .replace("HOOKS", hooks).replace("TITLE", str(meta.get("title", ""))))
    meta["ai_review"] = verdict
    if not verdict:
        meta["status"] = "pending"          # never auto-post without an AI look
        log.warning("[%s] AI review unavailable - left pending", clip_id)
    else:
        ok = bool(verdict.get("approve")) and int(verdict.get("score", 0)) >= cfg["auto"]["min_score"]
        if ok and not meta.get("ai"):   # template hooks ("X did not see this coming") never auto-post
            ok = False
            verdict.setdefault("problems", []).append("no AI-written hooks (AI was unavailable)")
        meta["tier"] = "gameplay"
        if any_topic:
            # non-GTA clip from a top streamer: only as a variety clip, only the viral kinds, higher score
            meta["tier"] = "backup"
            if ok and not (str(verdict.get("kind")) in ("music_reaction", "culture", "reaction", "romance")
                           and int(verdict.get("score", 0)) >= cfg["auto"].get("backup_min_score", 8)):
                ok = False
                verdict["reason"] = "not viral enough for a non-GTA clip: " + str(verdict.get("reason", ""))
        elif verdict.get("is_gta6") is False or (ok and _OTHER_GAME.search(str(verdict.get("new_title") or ""))):
            # Another game on a "GTA" stream. It must not go out with GTA 6 wording and tags - but a strong
            # moment is still wanted as a variety clip, so judge it once more under the non-GTA rules.
            if cfg["auto"].get("other_games_as_variety", True) and not meta.get("rerouted"):
                credit = [ln for ln in str(meta.get("caption", "")).splitlines() if ln.startswith("\U0001f3a5")]
                meta.update(topic="any", rerouted=True,
                            caption="\n".join([f"Clipped from {meta['channel']}'s stream", *credit]),
                            hashtags=[t for t in meta.get("hashtags", []) if not re.match(
                                r"(?i)gta|vicecity|grandtheft|rockstar", t)] + ["reaction"])
                save(meta)
                log.info("[%s] not GTA 6 - reviewing again as a non-GTA variety clip", clip_id)
                return auto_review(clip_id, cfg, src)
            ok = False
            verdict["reason"] = "not GTA 6: " + str(verdict.get("reason", ""))
        elif ok and cfg["auto"].get("gameplay_only", True) and verdict.get("gameplay") is not True:
            # No game on screen. Keep it as a "variety" clip (tier "backup") if it is about GTA 6 and
            # scores higher: music reactions, cultural references, viral talk. Variety clips fill runs
            # with no gameplay clip ready, and every [auto] variety_every-th post (see _variety_due).
            backup = (cfg["auto"].get("backup_when_no_gameplay", True) and verdict.get("gta_related") is True
                      and verdict.get("trailer_reaction") is not True   # copyright-claim risk
                      and int(verdict.get("score", 0)) >= cfg["auto"].get("backup_min_score", 8))
            if backup:
                meta["tier"] = "backup"
            else:
                ok = False
                verdict["reason"] = "no gameplay on screen: " + str(verdict.get("reason", ""))
        new_title = str(verdict.get("new_title") or "").strip()
        if ok and 8 <= len(new_title) <= 100 and new_title != meta.get("title"):
            log.info("[%s] title corrected: %r -> %r", clip_id, meta.get("title"), new_title)
            meta["title_written"], meta["title"] = meta.get("title"), new_title[:90]
        meta["theme"] = verdict.get("theme") is True
        meta["kind"] = str(verdict.get("kind") or ("gameplay" if verdict.get("gameplay") else "other"))[:30]
        meta["status"] = "approved" if ok else "rejected"
        best = int(verdict.get("best_hook", 1) or 1)
        meta["variant"] = best if 1 <= best <= len(meta["hooks"]) else 1
        if ok and src is not None:
            from . import edit
            dur = meta["end"] - meta["start"]
            try:
                at = min(max(float(verdict.get("thumbnail_second", dur / 3)), 0.5), dur - 0.5)
            except (TypeError, ValueError):
                at = dur / 3
            text, thumb = meta["hooks"][meta["variant"] - 1]["text"], QUEUE / clip_id / "thumb.jpg"
            try:
                edit.thumbnail(src, meta["start"] + at, cfg, meta.get("facecam"), text, thumb)
            except Exception:
                try:   # fall back to a frame of the finished clip
                    edit.thumbnail(QUEUE / clip_id / f"v{meta['variant']}.mp4", at, cfg, None, text, thumb, raw=True)
                except Exception as e:
                    log.warning("[%s] thumbnail failed: %s", clip_id, e)
        log.info("[%s] AI %s%s (score %s): %s", clip_id, meta["status"].upper(),
                 f" as VARIETY ({meta['kind']})" if ok and meta["tier"] == "backup" else "",
                 verdict.get("score"), verdict.get("reason", ""))
    save(meta)
    return meta


PERFORMANCE: dict[str, int] = {}   # streamer -> 0/1/2 from real view counts (stats.channel_buckets), set by batch


def _rank(m: dict, cfg: dict, variety_due: bool = False):
    """Posting order: gameplay before variety clips (the other way round when a variety post is due),
    then clips on the channel's [auto] themes, then streamers whose Shorts get the most views (and last,
    those that clearly get the fewest), then [auto] priority_channels, then best score, newest."""
    top = [c.lower() for c in cfg["auto"].get("priority_channels", [])]
    on_theme = bool(cfg["auto"].get("themes")) and m.get("theme") is True
    ch = str(m.get("channel", "")).lower()
    return ((m.get("tier") == "backup") != variety_due, not on_theme, -PERFORMANCE.get(ch, 1),
            ch not in top, -(m.get("ai_review") or {}).get("score", 0), -m["created"])


def _variety_due(cfg: dict, platform: str) -> bool:
    """True when the last (variety_every - 1) posts were all gameplay, so the next one may be a variety clip
    (music reaction, cultural reference, viral talk). variety_every = 0 turns the mix off."""
    n = int(cfg["auto"].get("variety_every", 0))
    if n < 2:
        return False
    hist = [h for h in _history() if h["platform"] == platform]
    last = hist[-(n - 1):]
    return len(last) == n - 1 and all(h.get("tier", "gameplay") != "backup" for h in last)


# ---- posting ----------------------------------------------------------------
def quota_day() -> str:
    """YouTube's upload quota resets at midnight Pacific time, so caps count Pacific days."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _history() -> list[dict]:
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def _cap(cfg: dict, platform: str) -> int:
    """Daily cap; [safety.cap_overrides."YYYY-MM-DD"] sets a different cap for one (Pacific) day."""
    day = cfg["safety"].get("cap_overrides", {}).get(quota_day(), {})
    return int(day.get(platform, cfg["safety"]["daily_caps"].get(platform, 0)))


def _can_post(cfg: dict, platform: str, respect_gap: bool = True) -> str | None:
    hist = [h for h in _history() if h["platform"] == platform]
    today = quota_day()
    if sum(1 for h in hist if h["date"] == today) >= _cap(cfg, platform):
        return f"daily cap {_cap(cfg, platform)} reached"
    gap = cfg["safety"]["min_minutes_between_posts"] * 60
    if respect_gap and hist and time.time() - hist[-1].get("at", 0) < gap:
        return "too soon after last post"
    return None


def _limit_error(err: str) -> bool:
    """The platform refused because of an upload limit (API quota, or the channel's own daily
    upload limit) - nothing wrong with the clip, so it must not use up the clip's tries."""
    e = str(err).lower()
    return any(k in e for k in ("quota", "429", "ratelimitexceeded", "uploadlimitexceeded",
                                "exceeded the number of videos"))


def _retryable(m: dict, platform: str) -> bool:
    if m.get("topic") != "any" and _OTHER_GAME.search(str(m.get("title", ""))):
        return False   # approved before the "is it really GTA 6" rule: never post it with GTA 6 tags
    p = m["posts"].get(platform, {})
    return p.get("tries", 0) < 2 or _limit_error(p.get("error", ""))


_BLOCKED: set[str] = set()   # platforms that refused an upload for quota reasons during this run


def _post_one(meta: dict, platform: str, variant: int, cfg: dict) -> bool:
    from .uploaders import UPLOADERS

    video = QUEUE / meta["id"] / f"v{variant}.mp4"
    hook = meta["hooks"][variant - 1]
    try:
        result = UPLOADERS[platform](video, meta, cfg)
    except Exception as e:
        err = str(e)
        quota = _limit_error(err)
        tries = meta["posts"].get(platform, {}).get("tries", 0) + (0 if quota else 1)   # a full quota isn't the clip's fault
        meta["posts"][platform] = {"ok": False, "error": err[:500], "at": time.time(), "tries": tries}
        log.error("[%s] %s upload FAILED: %s", meta["id"], platform, err[:300])
        save(meta)
        if quota:
            _BLOCKED.add(platform)   # stop uploading there for the rest of this run
            log.warning("%s upload quota is used up - no more uploads this run", platform)
            notify.send(f"{platform} upload limit reached", "No more uploads until the quota frees up. "
                        "The clip stays queued for a later run.", tags=["hourglass"])
        else:
            notify.send(f"Upload failed ({platform})", f"{meta.get('title', meta['id'])}\n{err[:300]}",
                        tags=["warning"], priority=4)
        return False
    meta["posts"][platform] = {"ok": True, "variant": variant, "hook_structure": hook["structure"],
                               "result": result, "at": time.time()}
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(_history() + [{
        "id": meta["id"], "platform": platform, "date": quota_day(), "at": time.time(),
        "hook_structure": hook["structure"], "channel": meta["channel"], "result": result,
        "title": meta.get("title", ""), "tier": meta.get("tier", "gameplay"), "kind": meta.get("kind", ""), "theme": bool(meta.get("theme")),
        "score": (meta.get("ai_review") or {}).get("score")}], indent=2))
    if all(meta["posts"].get(p, {}).get("ok") for p in cfg["upload"]["platforms"]):
        meta["status"] = "posted"
    save(meta)
    log.info("[%s] posted to %s: %s", meta["id"], platform, result)
    today = sum(1 for h in _history() if h["platform"] == platform and h["date"] == quota_day())
    notify.send(f"Posted: {meta.get('title', meta['id'])}",
                f"{meta['channel']} - {meta.get('tier', 'gameplay')} - AI score {(meta.get('ai_review') or {}).get('score', '?')}"
                f"\n{platform} today: {today}/{_cap(cfg, platform)}",
                click=result if str(result).startswith("http") else None, tags=["clapper"])
    return True


def post_due(cfg: dict) -> None:
    """Post at most one approved clip per platform, best score first, if caps/spacing allow."""
    max_age = cfg["auto"]["max_age_hours"] * 3600
    ready = [m for m in items("approved") if time.time() - m["created"] < max_age]
    ready.sort(key=lambda m: _rank(m, cfg))
    for platform in cfg["upload"]["platforms"]:
        if _can_post(cfg, platform) or platform in _BLOCKED:
            continue
        for m in ready:
            if not m["posts"].get(platform, {}).get("ok") and _retryable(m, platform):
                m["posts"].setdefault(platform, {})
                _post_one(m, platform, m.get("variant", 1), cfg)   # counts its own failed tries
                break


def post_batch(cfg: dict, n: int, done: dict | None = None, backups: bool = True) -> dict:
    """Batch runs: post up to n best approved clips per platform now (daily caps and spacing apply).
    `done` = how many this run already posted per platform, so it can be called after every source."""
    done = done if done is not None else {}
    max_age = cfg["auto"]["max_age_hours"] * 3600
    for platform in cfg["upload"]["platforms"]:
        posted = done.get(platform, 0)
        failures = 0
        while (posted < n and failures < 3 and platform not in _BLOCKED
               and not _can_post(cfg, platform, respect_gap=True)):
            due = _variety_due(cfg, platform)
            ready = [m for m in items("approved") if time.time() - m["created"] < max_age
                     and not m["posts"].get(platform, {}).get("ok")
                     and _retryable(m, platform)
                     and (backups or due or m.get("tier") != "backup")]
            if not ready:
                break
            ready.sort(key=lambda m: _rank(m, cfg, due))
            m = ready[0]
            if _post_one(m, platform, m.get("variant", 1), cfg):   # counts its own failed tries
                posted += 1
            else:
                failures += 1
        done[platform] = posted
    return done


def post_now(clip_id: str, variant: int, platforms: list[str], cfg: dict) -> None:
    """Manual approve: post immediately (daily caps still apply)."""
    meta = load(clip_id)
    meta["status"], meta["variant"] = "approved", variant
    for p in platforms:
        why = _can_post(cfg, p, respect_gap=False)
        if why:
            print(f"  {p}: skipped ({why})")
        elif _post_one(meta, p, variant, cfg):
            print(f"  {p}: {meta['posts'][p]['result']}")
        else:
            print(f"  {p}: FAILED - {meta['posts'][p]['error']}")


# ---- cleanup ----------------------------------------------------------------
def cleanup(cfg: dict) -> None:
    keep = cfg["storage"]
    now = time.time()
    for m in items():
        age_h = (now - m["created"]) / 3600
        limit = {"posted": keep["posted_hours"], "rejected": keep["rejected_hours"]}.get(
            m["status"], keep["unposted_hours"])
        if age_h > limit:
            shutil.rmtree(QUEUE / m["id"], ignore_errors=True)
    for d in (ROOT / "output" / "vods").glob("*"):
        if now - d.stat().st_mtime > keep["vod_hours"] * 3600:
            shutil.rmtree(d, ignore_errors=True)
