"""Cheap, model-free signals on a 0.5 s grid. Every function returns a 1-D array
with one value per HOP seconds of video, so they can be summed into one score.

- loudness: RMS vs a trailing 3-min baseline (+60 % rule) and a z-score
- visual:   frame-diff motion, scene-cut density, HUD-region change, ad slates
- chat:     unique chatters per window (VOD replay chat or live)
- heatmap:  YouTube "most replayed" curve when yt-dlp provides it
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

HOP = 0.5          # seconds per bin; visual sampling is 1/HOP fps
SR = 8000          # audio sample rate for loudness
VW, VH = 160, 90   # analysis frame size


def _ff_input(src: Path, start: float, dur: float | None) -> list[str]:
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}"]
    if dur:
        args += ["-t", f"{dur:.3f}"]
    return args + ["-i", str(src)]


def _trailing(x: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Trailing mean and std over the previous n bins (excluding current)."""
    c1 = np.concatenate([[0.0], np.cumsum(x)])
    c2 = np.concatenate([[0.0], np.cumsum(x * x)])
    idx = np.arange(len(x))
    lo = np.maximum(idx - n, 0)
    cnt = np.maximum(idx - lo, 1)
    mean = (c1[idx] - c1[lo]) / cnt
    var = np.maximum((c2[idx] - c2[lo]) / cnt - mean ** 2, 1e-9)
    mean[0] = x[0]
    return mean, np.sqrt(var)


def robust_z(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826 + 1e-6
    return np.clip((x - med) / mad, 0, 8)


def smooth(x: np.ndarray, seconds: float) -> np.ndarray:
    n = max(1, int(seconds / HOP))
    return np.convolve(x, np.ones(n) / n, mode="same") if len(x) else x


# ---- audio ------------------------------------------------------------------
def loudness(src: Path, start: float = 0, dur: float | None = None, baseline_s: float = 180) -> np.ndarray:
    raw = subprocess.run(
        _ff_input(src, start, dur) + ["-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    n = int(SR * HOP)
    bins = len(a) // n
    if bins == 0:
        return np.zeros(0)
    rms = np.sqrt((a[: bins * n].reshape(bins, n) ** 2).mean(1)) + 1e-5
    db = 20 * np.log10(rms)
    base_lin, _ = _trailing(rms, int(baseline_s / HOP))
    mean_db, std_db = _trailing(db, int(baseline_s / HOP))
    z = np.clip((db - mean_db) / np.maximum(std_db, 3.0), 0, 30)
    spike = rms >= 1.6 * base_lin          # +60 % over the 3-min baseline
    return np.where(spike, z, z * 0.4)


# ---- video ------------------------------------------------------------------
def visual(src: Path, cfg: dict, start: float = 0, dur: float | None = None) -> dict[str, np.ndarray]:
    """One streaming pass over frames at 2 fps. Returns motion, scene, hud, ad_slate arrays."""
    v = cfg["signals"]
    x0, y0, x1, y1 = v["hud_region"]
    hx0, hy0, hx1, hy1 = int(x0 * VW), int(y0 * VH), max(int(x1 * VW), int(x0 * VW) + 1), max(int(y1 * VH), int(y0 * VH) + 1)
    proc = subprocess.Popen(
        _ff_input(src, start, dur) + ["-an", "-vf", f"fps={1 / HOP},scale={VW}:{VH}",
                                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    size = VW * VH * 3
    motion, scene, hud, slate = [], [], [], []
    prev_g = prev_h = None
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, np.uint8).reshape(VH, VW, 3).astype(np.int16)
        g = f.mean(2)
        h = f[hy0:hy1, hx0:hx1]
        d = float(np.abs(g - prev_g).mean()) if prev_g is not None else 0.0
        motion.append(d)
        scene.append(1.0 if d > v["scene_cut_diff"] else 0.0)
        hud.append(float(np.abs(h - prev_h).mean()) if prev_h is not None else 0.0)
        # Twitch ad slate: blue-heavy, near-flat at 32x18
        small = f.reshape(18, 5, 32, 5, 3).mean((1, 3))
        r, gg, b = small[..., 0].mean() + 1, small[..., 1].mean() + 1, small[..., 2].mean()
        flat = np.abs(np.diff(small.mean(2), axis=1)).mean()
        slate.append(1.0 if (b > 1.8 * r and b > 1.6 * gg and flat < 13) else 0.0)
        prev_g, prev_h = g, h
    proc.wait()

    slate_a = np.array(slate)
    # keep only slate runs of >= 5 s
    run_min = int(5 / HOP)
    mask = np.zeros_like(slate_a)
    i = 0
    while i < len(slate_a):
        if slate_a[i]:
            j = i
            while j < len(slate_a) and slate_a[j]:
                j += 1
            if j - i >= run_min:
                mask[i:j] = 1
            i = j
        else:
            i += 1
    scene_a = np.array(scene)
    return {
        "motion": np.array(motion),
        "scene": np.convolve(scene_a, np.ones(int(10 / HOP)), mode="same"),  # cuts per 10 s
        "hud": np.array(hud),
        "ad_slate": mask,
    }


# ---- chat -------------------------------------------------------------------
def chat_from_file(path: Path) -> list[tuple[float, str]]:
    """Parse yt-dlp replay chat: YouTube live_chat.json (JSON lines) or Twitch rechat JSON."""
    out: list[tuple[float, str]] = []
    text = path.read_text(errors="replace")
    try:
        data = json.loads(text)
        for c in data.get("comments", []) if isinstance(data, dict) else data:
            t = c.get("content_offset_seconds") or c.get("contentOffsetSeconds")
            who = (c.get("commenter") or {}).get("display_name") or c.get("commenter", {}).get("displayName", "")
            if t is not None:
                out.append((float(t), who or "?"))
        return out
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():  # YouTube: one JSON object per line
        try:
            o = json.loads(line)
            act = o["replayChatItemAction"]
            t = int(act["videoOffsetTimeMsec"]) / 1000
            item = act["actions"][0]["addChatItemAction"]["item"]
            r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer") or {}
            who = r.get("authorExternalChannelId") or r.get("authorName", {}).get("simpleText", "?")
            out.append((t, who))
        except (KeyError, IndexError, ValueError, TypeError):
            continue
    return out


def chat_bursts(messages: list[tuple[float, str]], n_bins: int, window_s: float = 10, lag_s: float = 6) -> np.ndarray:
    """Unique chatters in a sliding window, shifted back by chat reaction lag."""
    arr = np.zeros(n_bins)
    if not messages:
        return arr
    w = int(window_s / HOP)
    per_bin: list[set] = [set() for _ in range(n_bins)]
    for t, who in messages:
        i = int((t - lag_s) / HOP)
        if 0 <= i < n_bins:
            per_bin[i].add(who)
    for i in range(n_bins):
        s = set().union(*per_bin[max(0, i - w // 2): i + w // 2 + 1])
        arr[i] = len(s)
    return arr


# ---- heatmap ----------------------------------------------------------------
def heatmap(info_json: Path, n_bins: int) -> np.ndarray:
    arr = np.zeros(n_bins)
    try:
        hm = json.loads(info_json.read_text()).get("heatmap") or []
    except (OSError, json.JSONDecodeError):
        return arr
    for seg in hm:
        a, b = int(seg["start_time"] / HOP), int(seg["end_time"] / HOP)
        arr[max(a, 0): min(b + 1, n_bins)] = seg["value"]
    return arr
