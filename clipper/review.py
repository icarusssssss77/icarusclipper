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
from datetime import date
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

Hooks (the white banner text; the video shows hook 1, the others are alternatives):
HOOKS

Return JSON: {"approve": bool, "score": 1-10 (how likely a stranger watches to the end),
"best_hook": 1-3, "problems": [short strings], "reason": "one sentence"}"""


def auto_review(clip_id: str, cfg: dict) -> dict:
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
        meta["status"] = "approved" if ok else "rejected"
        best = int(verdict.get("best_hook", 1) or 1)
        meta["variant"] = best if 1 <= best <= len(meta["hooks"]) else 1
        log.info("[%s] AI %s (score %s): %s", clip_id, meta["status"].upper(),
                 verdict.get("score"), verdict.get("reason", ""))
    save(meta)
    return meta


# ---- posting ----------------------------------------------------------------
def _history() -> list[dict]:
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def _cap(cfg: dict, platform: str) -> int:
    return int(cfg["safety"]["daily_caps"].get(platform, 0))


def _can_post(cfg: dict, platform: str, respect_gap: bool = True) -> str | None:
    hist = [h for h in _history() if h["platform"] == platform]
    today = date.today().isoformat()
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
        "id": meta["id"], "platform": platform, "date": date.today().isoformat(), "at": time.time(),
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
    ready.sort(key=lambda m: (-(m.get("ai_review") or {}).get("score", 0), -m["created"]))
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
