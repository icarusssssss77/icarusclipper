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


def parse_channel(ch: str) -> tuple[str, str, bool]:
    """'xqc' -> Twitch; or a URL like 'youtube.com/@IShowSpeed/live', 'kick.com/adinross'.
    Returns (name, live_url, is_twitch)."""
    if "/" in ch or "." in ch:
        url = ch if "://" in ch else f"https://{ch}"
        parts = [p for p in url.split("/")[3:] if p and p != "live"]
        name = (parts[0] if parts else url.split("/")[2]).lstrip("@").lower()
        return name, url, "twitch.tv" in url
    return ch.lower(), f"https://twitch.tv/{ch.lower()}", True


def live_info(url: str) -> dict | None:
    """Stream metadata (title, category) if live, else None."""
    try:
        out = subprocess.run(["streamlink", "--json", "--loglevel", "error", url],
                             capture_output=True, text=True, timeout=60)
        d = json.loads(out.stdout) if out.stdout else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    return d.get("metadata") or {} if d.get("streams") else None


def is_gta(meta: dict) -> bool:
    """Category decides when the platform gives a real game (Twitch/Kick); otherwise use the title
    (YouTube only says 'Gaming')."""
    cat = (meta.get("category") or "").lower().strip()
    text = cat if cat and cat != "gaming" else (meta.get("title") or "").lower()
    return "grand theft auto" in text or "gta" in text


def is_live(url: str) -> bool:
    return live_info(url) is not None


def download_section(url: str, start: float, end: float, out: Path) -> Path | None:
    """Download one part of a VOD. Stream copy (no re-encode) so a 45 min part takes a few minutes;
    a slow or stuck download gives up instead of failing the run (the caller then tries the live stream)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(["yt-dlp", "--no-warnings", "-q", "-f", "720p/720p30/720p60/best[height<=720]/best",
                            "--download-sections", f"*{int(start)}-{int(end)}",
                            "-o", str(out), url], timeout=900)
    except subprocess.TimeoutExpired:
        log.warning("VOD download timed out after 15 min: %s", url)
        for f in out.parent.glob(out.stem + ".*"):
            f.unlink(missing_ok=True)
        return None
    return out if r.returncode == 0 and out.exists() else None


def record_live(url: str, minutes: float, out: Path) -> Path | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    sl = subprocess.Popen(["streamlink", "--stdout", "--loglevel", "error", url,
                           "720p,720p60,best"], stdout=subprocess.PIPE)
    ff = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", "pipe:0",
                         "-t", str(int(minutes * 60)), "-c", "copy", str(out)], stdin=sl.stdout)
    sl.kill()
    return out if ff.returncode == 0 and out.exists() and out.stat().st_size > 1_000_000 else None


def run(cfg: dict) -> None:
    b = cfg["batch"]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    shutil.rmtree(WORK, ignore_errors=True)
    sources: list[tuple[str, Path, str]] = []          # (channel, file, credit link)
    to_record: list[tuple[str, str]] = []              # (channel, live url)
    seen: set[str] = set()

    for ch in cfg["stream"]["channels"]:               # list order = priority (biggest first)
        if len(sources) + len(to_record) >= b["max_channels"]:
            break
        name, url, twitch = parse_channel(ch)
        if name in seen:
            continue
        if twitch:   # just-ended Twitch broadcasts: clip the saved VOD
            vod = latest_vod(name)
            if vod and vod["ended_ago"] < b["recent_hours"] * 3600:
                done_until = float(state.get(vod["id"], 0))
                start = max(done_until, vod["duration"] - b["minutes"] * 60)
                if vod["duration"] - start >= b["min_new_minutes"] * 60:
                    log.info("[%s] VOD %s: clipping %.0f-%.0f min", name, vod["id"], start / 60, vod["duration"] / 60)
                    f = download_section(vod["url"], start, vod["duration"], WORK / f"{name}.mp4")
                    if f:
                        state[vod["id"]] = vod["duration"]
                        sources.append((name, f, f"https://twitch.tv/{name}"))
                        seen.add(name)
                        continue
        meta = live_info(url)
        if meta is None:
            log.info("[%s] not live", name)
        elif b.get("only_gta", True) and not is_gta(meta):
            log.info("[%s] live but not playing GTA (%s)", name, meta.get("category") or meta.get("title"))
        else:
            to_record.append((name, url))
            seen.add(name)

    if to_record:   # live now: record all of them in parallel
        log.info("recording live for %s min: %s", b["live_record_minutes"], ", ".join(n for n, _ in to_record))
        results: dict[str, Path | None] = {}
        threads = [threading.Thread(target=lambda n=n, u=u: results.__setitem__(
            n, record_live(u, b["live_record_minutes"], WORK / f"{n}-live.ts"))) for n, u in to_record]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        links = dict(to_record)
        sources += [(n, f, links[n].removesuffix("/live")) for n, f in results.items() if f]

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))

    posted: dict = {}
    for ch, f, link in sources:
        try:
            pipeline.process_vod(str(f), cfg, ch, None, source_label=link)
        except Exception as e:
            log.exception("[%s] processing failed: %s", ch, e)
        f.unlink(missing_ok=True)
        posted = review.post_batch(cfg, b["posts_per_run"], posted, backups=False)   # gameplay clip ready: post now

    review.post_batch(cfg, b["posts_per_run"], posted)   # nothing posted yet: backups allowed
    review.cleanup(cfg)
    shutil.rmtree(WORK, ignore_errors=True)
