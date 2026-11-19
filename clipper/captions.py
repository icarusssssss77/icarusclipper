"""Speech-to-text with word timings (faster-whisper) and TikTok-style captions.

Captions are drawn as transparent PNGs with Pillow (one per spoken word, with
that word highlighted) and fed to ffmpeg as an image sequence, so this works
with any ffmpeg build, including Homebrew's, which has no libass/drawtext.
"""
from __future__ import annotations

import logging
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)


# ---- transcription ----------------------------------------------------------
@lru_cache(maxsize=1)
def _model(name: str):
    from faster_whisper import WhisperModel

    log.info("loading whisper model %s (first run downloads it)", name)
    return WhisperModel(name, device="cpu", compute_type="int8")


def extract_audio(src: Path, offset: float, duration: float, wav: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{offset:.3f}",
         "-t", f"{duration:.3f}", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )
    return wav


# GTA spelling fixes Whisper tends to get wrong
FIXES = {"gta": "GTA", "leonida": "Leonida", "lucia": "Lucia", "jason": "Jason", "vice": "Vice",
         "rockstar": "Rockstar", "gta6": "GTA 6", "vi": "6"}


def transcribe(wav: Path, model_name: str, vocab: str = "") -> list[dict]:
    import wave

    import numpy as np

    with wave.open(str(wav)) as wf:  # hand Whisper raw samples: avoids its PyAV decoder
        audio = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
    if len(audio) < 1600:
        return []
    segments, _ = _model(model_name).transcribe(
        audio, word_timestamps=True, vad_filter=True, language="en",
        initial_prompt=vocab or None,
    )
    words = []
    prev = ""
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            core = re.sub(r"\W", "", text).lower()
            if core in FIXES and (core != "vi" or prev == "gta"):
                text = re.sub(re.escape(re.sub(r"\W", "", text)), FIXES[core], text, count=1)
            prev = core
            words.append({"word": text, "start": float(w.start), "end": float(w.end)})
    return words


def censor(words: list[dict], bad: list[str]) -> list[dict]:
    if not bad:
        return words
    pat = re.compile(r"\b(" + "|".join(map(re.escape, bad)) + r")\w*", re.I)
    for w in words:
        w["word"] = pat.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), w["word"])
    return words


def chunk(words: list[dict], max_words: int) -> list[list[dict]]:
    """Group words into short on-screen phrases. Break on pauses and sentence ends."""
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > 0.6):
            out.append(cur)
            cur = []
        cur.append(w)
        if w["word"][-1:] in ".?!":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# ---- rendering --------------------------------------------------------------
def _draw(words: list[str], hi: int, c: dict, width: int, band_h: int) -> Image.Image:
    size = c["font_size"]
    img = Image.new("RGBA", (width, band_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # shrink the font until the phrase fits with side padding
    while True:
        font = ImageFont.truetype(c["font_path"], size)
        space = d.textlength(" ", font=font)
        widths = [d.textlength(w, font=font) for w in words]
        total = sum(widths) + space * (len(words) - 1)
        if total <= width - 120 or size <= 40:
            break
        size -= 4
    x = (width - total) / 2
    asc, desc = font.getmetrics()
    y = (band_h - (asc + desc)) / 2
    for i, (w, ww) in enumerate(zip(words, widths)):
        d.text(
            (x, y), w, font=font,
            fill=c["highlight_color"] if i == hi else c["text_color"],
            stroke_width=c["stroke_width"], stroke_fill=c["stroke_color"],
        )
        x += ww + space
    return img


def build_caption_track(words: list[dict], duration: float, cfg: dict, workdir: Path) -> tuple[Path, int, int] | None:
    """Writes PNGs + an ffmpeg concat list. Returns (list_path, band_height, y_position)."""
    c = cfg["captions"]
    width, height = cfg["edit"]["width"], cfg["edit"]["height"]
    if not words:
        return None
    band_h = int(c["font_size"] * 2.2)
    y = height - c["margin_bottom"] - band_h // 2
    capdir = workdir / "captions"
    capdir.mkdir(exist_ok=True)
    blank = capdir / "blank.png"
    Image.new("RGBA", (width, band_h), (0, 0, 0, 0)).save(blank)

    # timeline of (start, end, png)
    timeline: list[tuple[float, float, Path]] = []
    phrases = chunk(words, c["max_words_per_line"])
    n = 0
    for pi, ph in enumerate(phrases):
        labels = [w["word"].upper() for w in ph]
        next_phrase_start = phrases[pi + 1][0]["start"] if pi + 1 < len(phrases) else duration
        for wi, w in enumerate(ph):
            start = w["start"]
            if wi + 1 < len(ph):
                end = ph[wi + 1]["start"]
            else:
                end = min(w["end"] + 0.35, next_phrase_start)
            if end - start < 0.04:
                continue
            png = capdir / f"{n:05d}.png"
            _draw(labels, wi, c, width, band_h).save(png)
            timeline.append((max(0.0, start), min(end, duration), png))
            n += 1

    lines, t = [], 0.0
    for start, end, png in timeline:
        if start < t:
            start = t
        if end <= start:
            continue
        if start - t > 0.01:
            lines += [f"file '{blank}'", f"duration {start - t:.3f}"]
        lines += [f"file '{png}'", f"duration {end - start:.3f}"]
        t = end
    lines += [f"file '{blank}'", f"duration {max(duration - t, 0.05):.3f}", f"file '{blank}'"]
    listing = capdir / "track.txt"
    listing.write_text("\n".join(lines) + "\n")
    return listing, band_h, y
