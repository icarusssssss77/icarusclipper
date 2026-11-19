"""Rolling stream recorder.

streamlink pipes the live stream into ffmpeg, which writes short .ts segments
named by unix time (buffer/<channel>/<epoch>.ts). Old segments are deleted, so
we always have the last few minutes on disk and can cut a clip *backwards* in
time when chat spikes.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

from .config import ROOT

log = logging.getLogger(__name__)
SLOTS: threading.Semaphore | None = None   # caps how many streams record at once


def set_max_recordings(n: int) -> None:
    global SLOTS
    SLOTS = threading.BoundedSemaphore(n)


class StreamBuffer:
    def __init__(self, channel: str, cfg: dict):
        # accepts a Twitch name ("xqc") or any live URL streamlink knows (kick.com/x, youtube.com/@x/live)
        if "/" in channel or "." in channel:
            self.url = channel if "://" in channel else f"https://{channel}"
            parts = [p for p in self.url.split("/")[3:] if p and p != "live"]
            self.channel = (parts[0] if parts else self.url.split("/")[2]).lstrip("@").lower()
        else:
            self.channel = channel.lower()
            self.url = f"https://twitch.tv/{self.channel}"
        self.is_twitch = "twitch.tv" in self.url
        self.quality = cfg["stream"]["quality"]
        self.seg = cfg["clip"]["segment_seconds"]
        self.keep = cfg["clip"]["buffer_minutes"] * 60
        self.dir = ROOT / "buffer" / self.channel
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stop = threading.Event()
        self.live = False

    # ---- recording -------------------------------------------------------
    def start(self) -> None:
        threading.Thread(target=self._record_loop, daemon=True, name=f"rec-{self.channel}").start()
        threading.Thread(target=self._cleanup_loop, daemon=True, name=f"gc-{self.channel}").start()

    def _record_loop(self) -> None:
        while not self.stop.is_set():
            if SLOTS:
                SLOTS.acquire()
            try:
                pause = self._record_once()
            finally:
                if SLOTS:
                    SLOTS.release()
            self.stop.wait(pause)   # wait outside the slot so another channel can record

    def _record_once(self) -> float:
        if True:
            sl = subprocess.Popen(
                ["streamlink", "--stdout", "--loglevel", "error", self.url, self.quality],
                stdout=subprocess.PIPE,
            )
            ff = subprocess.Popen(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                    "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                    "-f", "segment", "-segment_time", str(self.seg), "-segment_format", "mpegts",
                    "-reset_timestamps", "1", "-strftime", "1", str(self.dir / "%s.ts"),
                ],
                stdin=sl.stdout,
            )
            sl.stdout.close()
            started = time.time()
            log.debug("[%s] recorder starting", self.channel)
            announced = False
            # health check: if no new segment lands for 45 s, kill and restart
            while ff.poll() is None and not self.stop.is_set():
                time.sleep(5)
                newest = max((p.stat().st_mtime for p in self.dir.glob("*.ts")), default=0)
                self.live = time.time() - newest < 3 * self.seg
                if self.live and not announced:
                    log.info("[%s] LIVE - recording", self.channel)
                    announced = True
                if time.time() - started > 60 and time.time() - newest > 45:
                    log.warning("[%s] recorder stalled, restarting", self.channel)
                    break
            for p in (ff, sl):
                if p.poll() is None:
                    p.kill()
            ff.wait()
            sl.wait()
            self.live = False
            if time.time() - started < 20:
                log.debug("[%s] offline, retrying in 60s", self.channel)
                return 60
            log.warning("[%s] recording stopped, restarting", self.channel)
            return 5

    def _cleanup_loop(self) -> None:
        while not self.stop.is_set():
            cutoff = time.time() - self.keep - 60
            for p in self.dir.glob("*.ts"):
                if p.stem.isdigit() and int(p.stem) < cutoff:
                    p.unlink(missing_ok=True)
            self.stop.wait(15)

    # ---- grabbing a clip --------------------------------------------------
    def grab(self, start: float, end: float, out: Path) -> tuple[Path, float]:
        """Concatenate the segments covering [start, end]. Returns (file, offset of `start` in it)."""
        times = sorted(int(p.stem) for p in self.dir.glob("*.ts") if p.stem.isdigit())
        if not times:
            raise RuntimeError(f"no buffered video for {self.channel}")
        chosen = []
        for i, t in enumerate(times):
            nxt = times[i + 1] if i + 1 < len(times) else time.time()
            if t <= end and nxt > start:
                chosen.append(t)
        if not chosen:
            raise RuntimeError("requested time is not in the buffer anymore")
        listing = out.with_suffix(".txt")
        listing.write_text("".join(f"file '{self.dir / f'{t}.ts'}'\n" for t in chosen))
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", str(out)],
            check=True,
        )
        listing.unlink(missing_ok=True)
        return out, max(0.0, start - chosen[0])
