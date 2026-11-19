"""Batch mode: run a few times a day (e.g. GitHub Actions on a schedule).

Each run:
  1. for each channel (list order): take the most recent part of its current/just-ended
     Twitch broadcast (the VOD), skipping what earlier runs already clipped;
     if the VOD isn't available but the channel is live, record the live stream for a while
  2. find moments, cut, caption, Gemini approves (same pipeline as `vod`)
  3. post the best approved clips (daily caps still apply)
State (what was already clipped, what was posted) lives in output/ and is kept
between runs by the workflow cache.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import pipeline, review
from .config import ROOT

log = logging.getLogger(__name__)
STATE = ROOT / "output" / "batch_state.json"
WORK = ROOT / "output" / "batch_work"


def _yt_json(args: list[str], timeout: int = 90) -> dict | None:
    try:
        out = subprocess.run(["yt-dlp", "-J", "--no-warnings", *args], capture_output=True,
                             text=True, timeout=timeout)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout else None
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def latest_vod(channel: str) -> dict | None:
    """Newest archived broadcast (may still be in progress) as {id, url, duration, ended_ago}."""
    lst = _yt_json(["--flat-playlist", "--playlist-items", "1",
                    f"https://www.twitch.tv/{channel}/videos?filter=archives&sort=time"])
    entries = (lst or {}).get("entries") or []
    if not entries:
        return None
    url = entries[0].get("url") or f"https://www.twitch.tv/videos/{entries[0]['id']}"
    info = _yt_json([url])
    if not info or not info.get("duration"):
        return None
    ended_ago = time.time() - (info.get("timestamp", 0) + info["duration"])
    return {"id": str(info["id"]), "url": url, "duration": float(info["duration"]), "ended_ago": ended_ago}


def is_live(channel: str) -> bool:
    out = subprocess.run(["streamlink", "--json", "--loglevel", "error", f"https://twitch.tv/{channel}"],
                         capture_output=True, text=True, timeout=60)
    return '"streams"' in out.stdout


def download_section(url: str, start: float, end: float, out: Path) -> Path | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["yt-dlp", "--no-warnings", "-q", "-f", "720p/720p30/720p60/best[height<=720]/best",
                        "--download-sections", f"*{int(start)}-{int(end)}", "--force-keyframes-at-cuts",
                        "-o", str(out), url], timeout=1800)
    return out if r.returncode == 0 and out.exists() else None


def record_live(channel: str, minutes: float, out: Path) -> Path | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    sl = subprocess.Popen(["streamlink", "--stdout", "--loglevel", "error", f"https://twitch.tv/{channel}",
                           "720p,720p60,best"], stdout=subprocess.PIPE)
    ff = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "pipe:0",
                         "-t", str(int(minutes * 60)), "-c", "copy", str(out)], stdin=sl.stdout)
    sl.kill()
    return out if ff.returncode == 0 and out.exists() and out.stat().st_size > 1_000_000 else None


def run(cfg: dict) -> None:
    b = cfg["batch"]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    shutil.rmtree(WORK, ignore_errors=True)
    sources: list[tuple[str, Path, str]] = []    # (channel, file, credit link)
    to_record: list[str] = []

    for ch in cfg["stream"]["channels"]:
        if "/" in ch or "." in ch:
            continue                              # batch mode: Twitch names only
        if len(sources) + len(to_record) >= b["max_channels"]:
            break
        vod = latest_vod(ch)
        if vod and vod["ended_ago"] < b["recent_hours"] * 3600:
            done_until = float(state.get(vod["id"], 0))
            start = max(done_until, vod["duration"] - b["minutes"] * 60)
            if vod["duration"] - start < b["min_new_minutes"] * 60:
                log.info("[%s] nothing new since last run", ch)
                continue
            log.info("[%s] VOD %s: clipping %.0f-%.0f min", ch, vod["id"], start / 60, vod["duration"] / 60)
            f = download_section(vod["url"], start, vod["duration"], WORK / f"{ch}.mp4")
            if f:
                state[vod["id"]] = vod["duration"]
                sources.append((ch, f, f"https://twitch.tv/{ch}"))
                continue
            log.warning("[%s] VOD download failed", ch)
        if is_live(ch):
            to_record.append(ch)
        else:
            log.info("[%s] not live, no recent VOD", ch)

    if to_record:   # VOD not available (sub-only/disabled): record live, all in parallel
        log.info("recording live for %s min: %s", b["live_record_minutes"], ", ".join(to_record))
        results: dict[str, Path | None] = {}
        threads = [threading.Thread(target=lambda c=c: results.__setitem__(
            c, record_live(c, b["live_record_minutes"], WORK / f"{c}-live.ts"))) for c in to_record]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        sources += [(c, f, f"https://twitch.tv/{c}") for c, f in results.items() if f]

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))

    for ch, f, link in sources:
        try:
            pipeline.process_vod(str(f), cfg, ch, None, source_label=link)
        except Exception as e:
            log.exception("[%s] processing failed: %s", ch, e)
        f.unlink(missing_ok=True)

    review.post_batch(cfg, b["posts_per_run"])
    review.cleanup(cfg)
    shutil.rmtree(WORK, ignore_errors=True)
