"""Views report for the Shorts this clipper posted, so settings can be judged on results.

Printed at the end of every batch run (see the "views report" lines in the run log):
one line per Short, then averages per streamer, per hook type and per tier.
View counts come from the YouTube API when the login allows it, else from the public page (yt-dlp).
"""
from __future__ import annotations

import json
import logging
import statistics
import subprocess
import time

from . import review

log = logging.getLogger(__name__)


def _video_id(result: str) -> str | None:
    return result.rsplit("/", 1)[-1] if "youtube.com/shorts/" in result else None


def _views_key(ids: list[str], key: str) -> dict[str, int]:
    """Public view counts with a plain API key (GitHub secret YOUTUBE_API_KEY): 1 quota unit per 50 videos."""
    import requests
    out: dict[str, int] = {}
    for i in range(0, len(ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=30,
                         params={"part": "statistics", "id": ",".join(ids[i:i + 50]), "key": key})
        r.raise_for_status()
        for it in r.json().get("items", []):
            out[it["id"]] = int(it["statistics"].get("viewCount", 0))
    return out


def _views_api(ids: list[str]) -> dict[str, int]:
    import os
    if os.environ.get("YOUTUBE_API_KEY", "").strip():
        return _views_key(ids, os.environ["YOUTUBE_API_KEY"].strip())
    from googleapiclient.discovery import build

    from .uploaders.youtube import _creds
    yt = build("youtube", "v3", credentials=_creds())
    out: dict[str, int] = {}
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
        for it in resp.get("items", []):
            out[it["id"]] = int(it["statistics"].get("viewCount", 0))
    return out


def _views_page(ids: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for vid in ids[-40:]:
        try:
            r = subprocess.run(["yt-dlp", "-J", "--no-warnings", "--skip-download",
                                f"https://www.youtube.com/shorts/{vid}"], capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and r.stdout:
                out[vid] = int(json.loads(r.stdout).get("view_count") or 0)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
            continue
    return out


def _views_feed(seed: list[str] | None = None) -> dict[str, int]:
    """View counts of the channel's latest uploads from its public feed (no key, no login)."""
    import re

    import requests
    f = review.QUEUE / "_channel_id.txt"
    if not f.exists():   # no upload since this was added: find the channel from one of its known Shorts
        vids = [v for v in (_video_id(str(h.get("result", ""))) for h in review._history()) if v] + list(seed or [])
        for vid in vids[-3:]:
            try:
                o = requests.get("https://www.youtube.com/oembed", timeout=20, params={
                    "url": f"https://www.youtube.com/shorts/{vid}", "format": "json"}).json()
                page = requests.get(o["author_url"], timeout=20, headers={"User-Agent": "Mozilla/5.0",
                                                                          "Accept-Language": "en-US"}).text
                m = re.search(r"channel_id=(UC[\w-]{22})", page) or re.search(r'"channelId":"(UC[\w-]{22})"', page)
                if m:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(m.group(1))
                    break
            except Exception as e:
                log.info("could not find the channel from Short %s (%s)", vid, str(e)[:80])
    if not f.exists():
        log.info("views feed: channel not known yet (it is saved at the next upload)")
        return {}
    r = requests.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": f.read_text().strip()},
                     timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    out: dict[str, int] = {}
    for entry in r.text.split("<entry>")[1:]:
        vid = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", entry)
        n = re.search(r'<media:statistics views="(\d+)"', entry)
        if vid and n:
            out[vid.group(1)] = int(n.group(1))
    return out


def _fetch(ids: list[str]) -> dict[str, int]:
    import os
    views: dict[str, int] = {}
    sources = [("feed", lambda: _views_feed(ids))]
    if os.environ.get("YOUTUBE_API_KEY", "").strip():
        sources.insert(0, ("api key", lambda: _views_api(ids)))
    for name, fn in sources:
        try:
            got = fn()
        except Exception as e:
            log.info("views via %s not available (%s)", name, str(e)[:100])
            continue
        for k, v in got.items():
            views.setdefault(k, v)
        if got:
            log.info("views: %d counts read via %s", len(got), name)
    return views


def refresh(seed: list[str] | None = None) -> None:
    """Write the newest view counts onto the upload history (kept between runs)."""
    hist = review._history()
    ids = [v for v in (_video_id(str(h.get("result", ""))) for h in hist if h.get("platform") == "youtube") if v]
    views = _fetch(ids + list(seed or []))
    if not views:
        return
    now = time.time()
    for h in hist:
        vid = _video_id(str(h.get("result", "")))
        if vid in views:
            h["views"], h["views_at"] = views[vid], now
    review.HISTORY.write_text(json.dumps(hist, indent=2))


def channel_buckets(min_clips: int = 3, min_age_h: float = 6) -> dict[str, int]:
    """Streamer -> 2 (clearly above the channel's typical Short), 1 (typical / not enough data), 0 (clearly below).
    Only Shorts whose views were read at least min_age_h after posting count."""
    by: dict[str, list[int]] = {}
    for h in review._history():
        if h.get("views") is not None and h.get("views_at", 0) - h.get("at", 0) >= min_age_h * 3600:
            by.setdefault(str(h.get("channel", "")).lower(), []).append(int(h["views"]))
    allv = [v for vs in by.values() for v in vs]
    if len(allv) < 8:
        return {}
    typical = statistics.median(allv)
    if typical < 30:   # nothing is being shown at all: differences of a few views are noise, not a signal
        return {}
    out = {}
    for ch, vs in by.items():
        if len(vs) >= min_clips:
            med = statistics.median(vs)
            out[ch] = 2 if med >= 1.5 * typical else 0 if med <= 0.5 * typical else 1
    return out


def report(cfg: dict) -> list[dict]:
    rows = []
    for h in review._history():
        vid = _video_id(str(h.get("result", ""))) if h.get("platform") == "youtube" else None
        if vid:
            rows.append({"id": vid, "channel": h.get("channel", "?"), "hook": h.get("hook_structure", "?"),
                         "tier": h.get("tier", "?"), "title": h.get("title", ""), "at": h.get("at", 0)})
    known = {r["id"] for r in rows}
    for vid in cfg.get("stats", {}).get("extra_videos", []):   # posted before the history existed
        if vid not in known:
            rows.append({"id": vid, "channel": "?", "hook": "?", "tier": "?", "title": "", "at": 0})
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    views = {_video_id(str(h.get("result", ""))): h["views"] for h in review._history() if h.get("views") is not None}
    views.update(_fetch(ids))
    if not views:
        log.warning("views report: could not read any view counts")
        return rows
    now = time.time()
    for r in rows:
        r["views"] = views.get(r["id"])
        r["age_h"] = round((now - r["at"]) / 3600, 1) if r["at"] else None
    seen = [r for r in rows if r["views"] is not None]
    log.info("views report: %d Shorts, %d views in total", len(seen), sum(r["views"] for r in seen))
    for r in sorted(seen, key=lambda r: -r["views"]):
        log.info("views report: %6d views  %5s h old  %-14s %-9s %-16s %s  %s", r["views"],
                 r["age_h"] if r["age_h"] is not None else "?", r["channel"], r["tier"], r["hook"], r["id"], r["title"][:50])
    for key in ("channel", "hook", "tier"):
        groups: dict[str, list[int]] = {}
        for r in seen:
            groups.setdefault(str(r[key]), []).append(r["views"])
        for name, v in sorted(groups.items(), key=lambda kv: -statistics.median(kv[1])):
            log.info("views report: by %-7s %-16s %2d Shorts  median %6d  best %6d", key, name, len(v),
                     statistics.median(v), max(v))
    b = channel_buckets()
    if b:
        log.info("views report: posting order now favours %s; holds back %s",
                 [c for c, x in b.items() if x == 2] or "nobody yet", [c for c, x in b.items() if x == 0] or "nobody")
    return rows
