"""Find a streamer facecam overlay with numpy only (idea from PeakCut).

An overlay has fixed borders (the same columns/rows show edges in every frame)
and its pixels change far less than gameplay. Returns a normalised (x, y, w, h)
box, or None unless it is found with high confidence.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

W, H, N = 320, 180, 24


def _peaks(profile: np.ndarray, k: int = 10) -> list[int]:
    thr = 2.2 * np.median(profile)
    idx = [i for i in range(1, len(profile) - 1)
           if profile[i] > thr and profile[i] >= profile[i - 1] and profile[i] >= profile[i + 1]]
    return sorted(idx, key=lambda i: -profile[i])[:k]


def detect(src: Path, start: float, duration: float) -> tuple[float, float, float, float] | None:
    fps = N / max(duration, 1)
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{duration:.2f}",
         "-i", str(src), "-vf", f"fps={fps:.5f},scale={W}:{H},format=gray",
         "-frames:v", str(N), "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    n = len(raw) // (W * H)
    if n < 6:
        return None
    F = np.frombuffer(raw[: n * W * H], np.uint8).reshape(n, H, W).astype(np.float32)

    col = np.median(np.abs(np.diff(F, axis=2)).sum(1), axis=0)
    row = np.median(np.abs(np.diff(F, axis=1)).sum(2), axis=0)
    xs = sorted(set(_peaks(col) + [0, W - 1]))
    ys = sorted(set(_peaks(row) + [0, H - 1]))
    std = F.std(0)
    game_med = float(np.median(std))
    frame_mean = float(F.mean())
    cut = max(6.0, 0.35 * game_med)
    high = max(3.0, 0.25 * game_med)

    best, best_key = None, None
    for i, x0 in enumerate(xs):
        for x1 in xs[i + 1:]:
            if not 0.12 <= (x1 - x0) / W <= 0.60:
                continue
            for j, y0 in enumerate(ys):
                for y1 in ys[j + 1:]:
                    if not 0.12 <= (y1 - y0) / H <= 0.60 or not 0.55 <= (x1 - x0) / (y1 - y0) <= 3.2:
                        continue
                    real = [v for v, edge in ((col[x0], x0 in (0, W - 1)), (col[min(x1, W - 2)], x1 >= W - 1),
                                              (row[y0], y0 in (0, H - 1)), (row[min(y1, H - 2)], y1 >= H - 1))
                            if not edge]
                    if len(real) < 2:
                        continue
                    inside = std[y0:y1, x0:x1]
                    med_in = float(np.median(inside))
                    if med_in > high or (inside > cut).mean() > 0.30:
                        continue
                    if med_in < 0.8:          # a real face moves; a static panel doesn't
                        continue
                    if not (x0 < 0.08 * W or x1 > 0.92 * W):   # facecams sit against a side
                        continue
                    if F[:, y0:y1, x0:x1].mean() < 0.3 * frame_mean:
                        continue
                    key = (min(real), (x1 - x0) * (y1 - y0))
                    if best_key is None or key > best_key:
                        best, best_key = (x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H), key
    return best
