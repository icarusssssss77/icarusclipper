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


def _views_api(ids: list[str]) -> dict[str, int]:
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
    try:
        views = _views_api(ids)
    except Exception as e:
        log.info("views via API not available (%s); reading the public pages", str(e)[:120])
        views = _views_page(ids)
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
    return rows
