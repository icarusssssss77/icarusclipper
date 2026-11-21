"""VOD mode + the shared 'render a picked clip into the review queue' step."""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from . import captions, edit, facecam, moments, review, signals
from .config import ROOT

log = logging.getLogger(__name__)


def duration(src: Path) -> float:
    """Length in seconds. Some downloaded sections report 'N/A' in the container header;
    then fall back to the streams' lengths, then to actually reading the file."""
    for entries in ("format=duration", "stream=duration"):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(src)],
                             capture_output=True, text=True)
        vals = [float(v) for v in out.stdout.split() if v.replace(".", "", 1).isdigit()]
        if vals:
            return max(vals)
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-map", "0:a:0?", "-map", "0:v:0?",
                          "-c", "copy", "-f", "null", "-"], capture_output=True, text=True)
    times = re.findall(r"time=(\d+):(\d+):([\d.]+)", out.stderr)
    if not times:
        raise ValueError(f"cannot read duration of {src}")
    h, m, sec = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(sec)


def render_clip(src: Path, clip: dict, cfg: dict, channel: str, source: str, topic: str = "gta") -> dict:
    clip_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    d = review.QUEUE / clip_id
    d.mkdir(parents=True, exist_ok=True)
    dur = clip["end"] - clip["start"]
    words = captions.censor([dict(w) for w in clip["words"]], cfg["captions"]["censor_words"])
    cap = captions.build_caption_track(words, dur, cfg, d)
    cam = None
    if cfg["edit"]["layout"] in ("auto", "facecam-stack"):
        cam = facecam.find(src, clip["start"], dur, cfg, channel)
    credit = edit.credit_png(f"@{channel}", cfg, d / "hookcredit.png") if cfg["hook"].get("credit", True) else None
    if credit:
        link = source.split(" ")[0].removeprefix("live:")
        clip["caption"] = f"{clip['caption']}\n🎥 Credit: @{channel}" + (f" {link}" if "://" in link else "")
    for i, h in enumerate(clip["hooks"], 1):
        png = edit.hook_png(h["text"], cfg, d / f"hook{i}.png")
        edit.render(src, clip["start"], dur, d / f"v{i}.mp4", cfg, cap, png, cam, credit)
    shutil.rmtree(d / "captions", ignore_errors=True)
    for p in d.glob("hook*.png"):
        p.unlink()
    meta = {
        "id": clip_id, "status": "pending", "channel": channel, "source": source,
        "created": time.time(), "start": round(clip["start"], 2), "end": round(clip["end"], 2),
        "score": clip["score"], "signal": clip["signal"], "ai": clip["ai"], "facecam": cam,
        "hooks": clip["hooks"], "title": clip["title"], "caption": clip["caption"],
        "hashtags": clip["hashtags"], "transcript": " ".join(w["word"] for w in words), "posts": {},
        "topic": topic,
    }
    review.save(meta)
    log.info("queued %s  score %s  '%s'", clip_id, clip["score"], clip["title"])
    return meta


def fetch(url: str, work: Path, section: str | None) -> tuple[Path, Path | None, Path | None]:
    work.mkdir(parents=True, exist_ok=True)
    cmd = ["yt-dlp", "--no-playlist", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
           "--merge-output-format", "mp4", "-o", str(work / "video.%(ext)s"),
           "--write-info-json", "--write-subs", "--sub-langs", "live_chat,rechat"]
    if section:
        cmd += ["--download-sections", f"*{section}"]
    subprocess.run(cmd + [url], check=True)
    video = next(work.glob("video.mp4"))
    info = next(work.glob("*.info.json"), None)
    chat = next((p for p in work.glob("video.*") if p.suffix in (".json",) and "info" not in p.name), None)
    return video, info, chat


def process_vod(inp: str, cfg: dict, channel: str | None, section: str | None,
                source_label: str | None = None, topic: str = "gta") -> list[dict]:
    if Path(inp).exists():
        src, info, chat = Path(inp), None, None
        channel = channel or Path(inp).stem
    else:
        work = ROOT / "output" / "vods" / uuid.uuid4().hex[:8]
        src, info, chat = fetch(inp, work, section)
        if info and not channel:
            channel = json.loads(info.read_text()).get("uploader") or "streamer"
    channel = channel or "streamer"
    length = duration(src)
    log.info("analysing %s (%.0f min)", src.name, length / 60)

    sig = {"loud": signals.loudness(src)}
    sig.update(signals.visual(src, cfg))
    n = len(sig["loud"])
    if chat:
        sig["chat"] = signals.chat_bursts(signals.chat_from_file(chat), n)
        log.info("replay chat: %s", chat.name)
    if info:
        sig["heat"] = signals.heatmap(info, n)
    total = moments.timeline(sig, cfg)
    c = cfg["clip"]
    cands = moments.peaks(total, c["vod_candidates"], c["min_gap_seconds"])
    log.info("%d candidate moments, asking AI to cut + hook them", len(cands))
    clips = moments.package(src, cands, cfg, channel, length, topic)
    keep = [x for x in clips if x["score"] >= 6][: c["clips_per_vod"]]
    if len(keep) < 3:
        keep = clips[: max(3, len(keep))]
    metas = []
    for cl in keep:   # one bad clip must not lose the others
        dur = cl["end"] - cl["start"]
        if not 5 <= dur <= c["max_len"] * 2:
            log.warning("skipping clip with a bad cut (%.1f-%.1f s)", cl["start"], cl["end"])
            continue
        try:
            m = render_clip(src, cl, cfg, channel, source_label or inp, topic)
            if cfg["auto"]["enabled"]:
                m = review.auto_review(m["id"], cfg, src)
            metas.append(m)
        except Exception as e:
            log.warning("clip failed, skipping it: %s", str(e)[:300])
    return metas
