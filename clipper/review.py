"""Clip queue, AI approval, spaced-out posting, disk cleanup.

Each clip lives in output/queue/<id>/ as v1/v2/v3.mp4 (one per hook) + meta.json.
status: pending -> approved | rejected -> posted

With [auto] enabled, Gemini WATCHES each clip and approves or rejects it. Approved
clips are posted one at a time, spaced out, within each platform's daily cap.
If Gemini can't review a clip, it is never auto-posted.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from . import llm
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

Reject (approve=false) if ANY of these: loading/menu/pause/map screens most of the time, an ad break
or "commercial break" slate, black or frozen video, nothing really happens, it cuts off mid-action
before the payoff, captions badly wrong, hateful/sexual content, or real personal info on screen.

GAMEPLAY RULE: gameplay = GTA 6 game footage is clearly visible on screen (the game world, the
player's character or vehicle, the HUD) for MOST of the clip, and the key moment happens IN the game.
A small facecam over the game is fine. It is NOT gameplay if the streamer is just talking to the camera,
sitting/lying in their room, reading chat, reacting to other videos, watching trailers, or talking
ABOUT GTA 6 without playing it - even if the topic is GTA 6. Set "gameplay" honestly.
Also set "gta_related": true only if the clip is clearly about GTA 6 (playing it, or the streamer
talking about / reacting to GTA 6 specifically). Other games or random chatting = false.
Set "trailer_reaction": true if the clip mostly shows an official trailer or someone else's video
(the streamer watching/reacting to it) rather than their own stream.

Hooks (the white banner text; the video shows hook 1, the others are alternatives):
HOOKS

best_hook = the hook that makes a scroller most curious WITHOUT spoiling the payoff.

Return JSON: {"approve": bool, "gameplay": bool, "gta_related": bool, "trailer_reaction": bool, "score": 1-10 (how likely a stranger watches to the end),
"best_hook": 1-3, "thumbnail_second": number (the most eye-catching moment, e.g. a big reaction or
crash, in seconds from the start), "problems": [short strings], "reason": "one sentence"}"""


def auto_review(clip_id: str, cfg: dict, src: Path | None = None) -> dict:
    meta = load(clip_id)
    src = QUEUE / clip_id / "v1.mp4"
    with tempfile.TemporaryDirectory() as td:
        proxy = Path(td) / "p.mp4"   # small copy so it fits in one free Gemini request
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                        "-vf", "scale=360:-2,fps=15", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
                        "-c:a", "aac", "-b:a", "48k", "-ac", "1", str(proxy)], check=True)
        hooks = "\n".join(f"{i}. {h['text']}" for i, h in enumerate(meta["hooks"], 1))
        verdict = llm.watch_video(cfg, proxy.read_bytes(), REVIEW_PROMPT.replace("HOOKS", hooks))
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
        if ok and cfg["auto"].get("gameplay_only", True) and verdict.get("gameplay") is not True:
            # No game on screen. Keep it only as a backup: about GTA 6 and a higher score. Backups are
            # posted only when a run has no gameplay clip ready (see _rank).
            backup = (cfg["auto"].get("backup_when_no_gameplay", True) and verdict.get("gta_related") is True
                      and verdict.get("trailer_reaction") is not True   # copyright-claim risk
                      and int(verdict.get("score", 0)) >= cfg["auto"].get("backup_min_score", 8))
            if backup:
                meta["tier"] = "backup"
            else:
                ok = False
                verdict["reason"] = "no gameplay on screen: " + str(verdict.get("reason", ""))
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
                 " as BACKUP (no gameplay)" if ok and meta["tier"] == "backup" else "",
                 verdict.get("score"), verdict.get("reason", ""))
    save(meta)
    return meta


def _rank(m: dict):
    """Posting order: gameplay clips first, backups only when no gameplay clip is ready; then best score, newest."""
    return (m.get("tier") == "backup", -(m.get("ai_review") or {}).get("score", 0), -m["created"])


# ---- posting ----------------------------------------------------------------
def quota_day() -> str:
    """YouTube's upload quota resets at midnight Pacific time, so caps count Pacific days."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _history() -> list[dict]:
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def _cap(cfg: dict, platform: str) -> int:
    return int(cfg["safety"]["daily_caps"].get(platform, 0))


def _can_post(cfg: dict, platform: str, respect_gap: bool = True) -> str | None:
    hist = [h for h in _history() if h["platform"] == platform]
    today = quota_day()
    if sum(1 for h in hist if h["date"] == today) >= _cap(cfg, platform):
        return f"daily cap {_cap(cfg, platform)} reached"
    gap = cfg["safety"]["min_minutes_between_posts"] * 60
    if respect_gap and hist and time.time() - hist[-1].get("at", 0) < gap:
        return "too soon after last post"
    return None


def _post_one(meta: dict, platform: str, variant: int, cfg: dict) -> bool:
    from .uploaders import UPLOADERS

    video = QUEUE / meta["id"] / f"v{variant}.mp4"
    hook = meta["hooks"][variant - 1]
    try:
        result = UPLOADERS[platform](video, meta, cfg)
    except Exception as e:
        meta["posts"][platform] = {"ok": False, "error": str(e), "at": time.time()}
        log.error("[%s] %s upload FAILED: %s", meta["id"], platform, e)
        save(meta)
        return False
    meta["posts"][platform] = {"ok": True, "variant": variant, "hook_structure": hook["structure"],
                               "result": result, "at": time.time()}
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(_history() + [{
        "id": meta["id"], "platform": platform, "date": quota_day(), "at": time.time(),
        "hook_structure": hook["structure"], "channel": meta["channel"], "result": result}], indent=2))
    if all(meta["posts"].get(p, {}).get("ok") for p in cfg["upload"]["platforms"]):
        meta["status"] = "posted"
    save(meta)
    log.info("[%s] posted to %s: %s", meta["id"], platform, result)
    return True


def post_due(cfg: dict) -> None:
    """Post at most one approved clip per platform, best score first, if caps/spacing allow."""
    max_age = cfg["auto"]["max_age_hours"] * 3600
    ready = [m for m in items("approved") if time.time() - m["created"] < max_age]
    ready.sort(key=_rank)
    for platform in cfg["upload"]["platforms"]:
        if _can_post(cfg, platform):
            continue
        for m in ready:
            if not m["posts"].get(platform, {}).get("ok") and m["posts"].get(platform, {}).get("tries", 0) < 2:
                m["posts"].setdefault(platform, {})
                if not _post_one(m, platform, m.get("variant", 1), cfg):
                    m["posts"][platform]["tries"] = m["posts"][platform].get("tries", 0) + 1
                    save(m)
                break


def post_batch(cfg: dict, n: int) -> None:
    """Batch runs: post up to n best approved clips per platform now (daily caps apply, no spacing)."""
    max_age = cfg["auto"]["max_age_hours"] * 3600
    for platform in cfg["upload"]["platforms"]:
        posted = 0
        while posted < n and not _can_post(cfg, platform, respect_gap=False):
            ready = [m for m in items("approved") if time.time() - m["created"] < max_age
                     and not m["posts"].get(platform, {}).get("ok")
                     and m["posts"].get(platform, {}).get("tries", 0) < 2]
            if not ready:
                break
            ready.sort(key=_rank)
            m = ready[0]
            if _post_one(m, platform, m.get("variant", 1), cfg):
                posted += 1
            else:
                m = load(m["id"])
                m["posts"][platform]["tries"] = m["posts"][platform].get("tries", 0) + 1
                save(m)


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
