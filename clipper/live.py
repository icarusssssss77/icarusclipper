"""Live mode: rolling recorder + Twitch chat spikes + 2-min signal chunks -> review queue."""
from __future__ import annotations

import logging
import queue
import threading
import time

from . import moments, pipeline, review, signals
from .capture import StreamBuffer
from .chat import twitch_chat
from .config import ROOT
from .detector import SpikeDetector

log = logging.getLogger(__name__)


class LiveClipper:
    def __init__(self, channel: str, cfg: dict, jobs: queue.Queue):
        self.cfg, self.jobs = cfg, jobs
        self.buf = StreamBuffer(channel, cfg)
        self.channel = self.buf.channel
        self.det = SpikeDetector(cfg)
        self.stop = threading.Event()
        self.recent: list[float] = []   # candidate times (epoch)

    def start(self) -> None:
        self.buf.start()
        if self.buf.is_twitch:   # Kick/YouTube: audio + visual signals only
            threading.Thread(target=twitch_chat, args=(self.channel, self._on_chat, self.stop), daemon=True).start()
        threading.Thread(target=self._chunk_loop, daemon=True).start()

    def _on_chat(self, text: str) -> None:
        spike = self.det.feed(text)
        if spike and self.buf.live:
            log.info("[%s] chat spike %.1fx", self.channel, spike["ratio"])
            self.candidate(spike["time"] - 4, f"chat {spike['ratio']}x")

    def candidate(self, t: float, why: str) -> None:
        c = self.cfg["clip"]
        now = time.time()
        self.recent = [x for x in self.recent if now - x < 3600]
        if any(abs(t - x) < c["min_gap_seconds"] for x in self.recent):
            return
        if len(self.recent) >= c["max_clips_per_hour"]:
            log.info("[%s] hourly clip cap reached", self.channel)
            return
        self.recent.append(t)
        self.jobs.put((self, t, why))

    def _chunk_loop(self) -> None:
        c = self.cfg["clip"]
        every = c["live_chunk_seconds"]
        while not self.stop.wait(every):
            if not self.buf.live:
                continue
            end = time.time() - c["segment_seconds"] - 2
            start = end - 180                       # 3 min context for baselines
            try:
                f, off = self.buf.grab(start, end, ROOT / "buffer" / f"{self.channel}-chunk.ts")
                sig = {"loud": signals.loudness(f)}
                sig.update(signals.visual(f, self.cfg))
                total = moments.timeline(sig, self.cfg)
                file_t0 = start - off
                for t, score in moments.peaks(total, 2, c["min_gap_seconds"], c["live_min_score"]):
                    abs_t = file_t0 + t
                    if abs_t >= end - every:          # only peaks in the newest chunk
                        log.info("[%s] signal peak %.1f", self.channel, score)
                        self.candidate(abs_t, f"signal {score:.1f}")
            except Exception as e:
                log.warning("[%s] chunk analysis failed: %s", self.channel, e)


def worker(jobs: queue.Queue, cfg: dict) -> None:
    while True:
        lc, t, why = jobs.get()
        try:
            wait = t + moments.POST + cfg["clip"]["segment_seconds"] + 3 - time.time()
            if wait > 0:
                time.sleep(wait)
            a, b = t - moments.PRE - 5, t + moments.POST + 2
            f, off = lc.buf.grab(a, b, ROOT / "buffer" / f"{lc.channel}-clip.ts")
            peak = (t - a) + off
            length = pipeline.duration(f)
            clips = moments.package(f, [(peak, 5.0)], cfg, lc.channel, length)
            for cl in clips[:1]:
                meta = pipeline.render_clip(f, cl, cfg, lc.channel, f"live:{lc.buf.url} ({why})")
                if cfg["auto"]["enabled"]:
                    review.auto_review(meta["id"], cfg)
        except Exception as e:
            log.exception("clip job failed: %s", e)


def run(cfg: dict, channels: list[str]) -> None:
    from . import capture

    jobs: queue.Queue = queue.Queue()
    capture.set_max_recordings(cfg["stream"]["max_live_recordings"])
    for ch in channels:
        LiveClipper(ch, cfg, jobs).start()
    threading.Thread(target=worker, args=(jobs, cfg), daemon=True).start()
    log.info("watching %s - clips go to output/queue/  (Ctrl+C to stop)", ", ".join(channels))
    try:
        while True:
            time.sleep(300)
            try:
                if cfg["auto"]["enabled"]:
                    review.post_due(cfg)
                review.cleanup(cfg)
            except Exception as e:
                log.exception("post/cleanup failed: %s", e)
    except KeyboardInterrupt:
        log.info("stopping")
