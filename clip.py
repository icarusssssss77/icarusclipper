#!/usr/bin/env python3
"""Icarus Clipper: long video -> best moments -> vertical captioned shorts.

Usage:
  python clip.py <video-url-or-file> [--top 3] [--len 30] [--credit "@streamer"]

Steps: download (yt-dlp) -> find loud/hype moments (audio energy) ->
cut -> transcribe (faster-whisper) -> 9:16 with blurred background ->
burn big captions -> out/<name>/clip_XX.mp4 + clip_XX.txt (title/caption).
Only use videos you have permission to clip.
"""
import argparse, json, re, subprocess, sys
from pathlib import Path

import numpy as np

W, H = 1080, 1920
HASHTAGS = "#GTA6 #GTAVI #GTA #gaming #shorts"


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def download(src, workdir):
    if Path(src).exists():
        return Path(src)
    import yt_dlp
    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b",
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(src, download=True)
        return Path(ydl.prepare_filename(info)).with_suffix(".mp4")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def find_moments(path, top, clip_len):
    """Score each second by loudness jump vs. its surroundings; pick top windows."""
    sr = 8000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    secs = len(a) // sr
    if secs < clip_len:
        return [0.0]
    rms = np.sqrt((a[: secs * sr].reshape(secs, sr) ** 2).mean(1) + 1e-9)
    db = 20 * np.log10(rms)
    base = np.convolve(db, np.ones(60) / 60, mode="same")          # 1-min background level
    hype = np.convolve(db - base, np.ones(5) / 5, mode="same")     # 5-s bursts above it
    window = np.convolve(hype, np.ones(clip_len), mode="valid")     # total hype per window
    picks = []
    for i in np.argsort(window)[::-1]:
        if all(abs(i - p) >= clip_len for p in picks):
            picks.append(int(i))
        if len(picks) == top:
            break
    # start 25% before the peak second so the build-up is included
    out = []
    for p in picks:
        peak = p + int(np.argmax(hype[p:p + clip_len]))
        start = max(0, min(peak - clip_len // 4, secs - clip_len))
        out.append(float(start))
    return sorted(out)


_MODELS = {}


def transcribe(path, model):
    from faster_whisper import WhisperModel
    m = _MODELS.get(model) or _MODELS.setdefault(model, WhisperModel(model, device="cpu", compute_type="int8"))
    # decode with ffmpeg ourselves (newer PyAV versions break faster-whisper's own loader)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if len(audio) < 1600:
        return []
    segs, _ = m.transcribe(audio, word_timestamps=True, vad_filter=True)
    return [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or []) if w.word.strip()]


def ts(t):
    h, r = divmod(max(t, 0), 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(words, path, clip_len, credit, hook=""):
    """Big centered word-group captions (3 words at a time), TikTok style."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial Black,96,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Hook,Arial Black,78,&H00000000,&H000000FF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,330,1
Style: Credit,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,0,8,40,40,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if credit:
        lines.append(f"Dialogue: 0,{ts(0)},{ts(clip_len)},Credit,,0,0,0,,{credit}")
    if hook:  # short hook on screen for the first 2.5 s
        lines.append(f"Dialogue: 2,{ts(0)},{ts(2.5)},Hook,,0,0,0,,{hook}")
    for i in range(0, len(words), 3):
        g = words[i:i + 3]
        nxt = words[i + 3][0] if i + 3 < len(words) else g[-1][1] + 0.4
        clean = [w.upper().replace("{", "").replace("}", "") for _, _, w in g]
        # one event per word: the spoken word turns yellow and pops slightly
        for k, (ws, we, _) in enumerate(g):
            end = g[k + 1][0] if k + 1 < len(g) else min(max(we, ws + 0.3), nxt)
            txt = " ".join((r"{\c&H00E5FF&\fscx112\fscy112}" + c + r"{\r}") if j == k else c
                           for j, c in enumerate(clean))
            lines.append(f"Dialogue: 1,{ts(ws)},{ts(end)},Cap,,0,0,0,,{{\\pos({W//2},{int(H*0.72)})}}{txt}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def render(src, start, clip_len, ass, out, mode):
    if mode == "crop":   # fill the screen, cut the sides
        vf = f"scale=-2:{H},crop={W}:{H}"
    else:                # gameplay centered on a blurred copy of itself
        vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"boxblur=25:5,eq=brightness=-0.15[bg];[b]scale={W}:-2[fg];[bg][fg]overlay=0:(H-h)/2")
    ass_esc = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    vf += f",subtitles='{ass_esc}'"
    run(["ffmpeg", "-y", "-ss", str(start), "-t", str(clip_len), "-i", str(src),
         "-filter_complex", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-b:a", "160k", "-r", "30", "-movflags", "+faststart", str(out)])


def make_hook(words):
    """2-6 word hook from the first spoken line, sentence case (ALL CAPS hooks do worse)."""
    said = " ".join(w for _, _, w in words).strip()
    first = re.split(r"(?<=[.!?])\s", said)[0] if said else ""
    ws = re.sub(r"[^\w' !?]", "", first).split()[:6]
    while len(ws) > 2 and ws[-1].lower() in {"the", "a", "an", "of", "to", "and", "off", "on", "in", "i", "my"}:
        ws.pop()
    if len(ws) < 2:
        return "Wait for it..."
    h = " ".join(ws)
    return h[0].upper() + h[1:].lower()


def caption_text(words, credit, hook, hooks=None):
    """3 title variants to A/B test (AI hooks if available, else templates)."""
    base = (hooks or []) + [hook, "Nobody expected this in GTA 6", "GTA 6 did this in under 30 seconds"]
    seen = []
    for h in base:
        if h and h.lower() not in [x.lower() for x in seen]:
            seen.append(h)
    titles = [f"{h} #Shorts" for h in seen[:3]]
    hook = seen[0]
    body = f"{hook}\n\n{('Credit: ' + credit) if credit else ''}\n{HASHTAGS}".strip()
    return titles, body


def make_clip(src, st, clip_len, od, tag, a, words=None, hooks=None):
    """Cut one moment from src -> od/tag.mp4 + .json/.txt. Returns the json path.
    words (optional) = already-transcribed words with times relative to st."""
    raw = od / f"{tag}_raw.wav"
    if words is None and a.no_captions:
        words = []
    elif words is None:
        print(f"   [{tag}] transcribing...")
        run(["ffmpeg", "-y", "-ss", str(st), "-t", str(clip_len), "-i", str(src),
             "-vn", "-ac", "1", "-ar", "16000", str(raw)])
        words = transcribe(raw, a.model); raw.unlink()
    if not hooks and getattr(a, "ai", False):
        import ai
        hooks = ai.hooks_for(" ".join(w for _, _, w in words), clip_len)
    hook = (hooks[0] if hooks else make_hook(words)) if (words or hooks) else ""
    ass = od / f"{tag}.ass"; write_ass(words, ass, clip_len, a.credit, hook)
    print(f"   [{tag}] rendering vertical clip...")
    render(src, st, clip_len, ass, od / f"{tag}.mp4", a.mode)
    titles, body = caption_text(words, a.credit, hook or "GTA 6 moment", hooks)
    meta = {"file": f"{tag}.mp4", "source": str(a.source), "start": st,
            "title": titles[0], "title_variants": titles, "caption": body}
    (od / f"{tag}.json").write_text(json.dumps(meta, indent=2))
    (od / f"{tag}.txt").write_text("TITLES (post one per platform, see which wins):\n- "
                                   + "\n- ".join(titles) + f"\n\nCAPTION:\n{body}\n")
    print(f"   done -> {od / (tag + '.mp4')}")
    return od / f"{tag}.json"


def ai_plan(src, a, clip_len):
    """Loudness finds 3x candidates (2x long), Whisper transcribes them, Claude picks the best."""
    import ai
    win = clip_len * 2
    cands = find_moments(src, a.top * 3, win)
    total = duration(src)
    texts = []
    for i, st in enumerate(cands):
        print(f"   transcribing candidate {i + 1}/{len(cands)}...")
        wav = Path(a.out) / "_cand.wav"
        run(["ffmpeg", "-y", "-ss", str(st), "-t", str(win), "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        ws = [(s0 + st, e0 + st, w) for s0, e0, w in transcribe(wav, a.model)]
        wav.unlink()
        texts.append((st, min(st + win, total), ws))
    print("   asking Claude to pick the best moments...")
    picks = ai.pick_moments([(s, e, " ".join(w for _, _, w in ws)) for s, e, ws in texts], a.top, clip_len)
    if not picks:
        print("   (Claude unavailable, using loudness picks)")
        return None
    plan = []
    for st, hooks, why in picks:
        st = max(0.0, min(st, total - clip_len))
        print(f"   {st:.0f}s: {why}")
        ws = next((w for s, e, w in texts if s <= st and st + clip_len <= e), None)
        words = [(s0 - st, e0 - st, w) for s0, e0, w in ws if st <= s0 < st + clip_len] if ws is not None else None
        plan.append((st, words, hooks))
    return sorted(plan)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="video URL or local file")
    ap.add_argument("--top", type=int, default=3, help="number of clips")
    ap.add_argument("--len", type=int, default=30, help="clip length in seconds")
    ap.add_argument("--start", type=float, action="append", help="force a start time (s); repeatable")
    ap.add_argument("--credit", default="", help='on-screen credit, e.g. "@streamer"')
    ap.add_argument("--model", default="small", help="whisper model: tiny/base/small/medium")
    ap.add_argument("--mode", choices=["blur", "crop"], default="blur")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--no-ai", dest="ai", action="store_false", help="skip Claude moment picks/hooks")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    out_root = Path(a.out); dl = out_root / "_downloads"; dl.mkdir(parents=True, exist_ok=True)
    print("1/3 getting video..."); src = download(a.source, dl)
    name = re.sub(r"\W+", "_", src.stem)[:40]; od = out_root / name; od.mkdir(exist_ok=True)
    clip_len = min(a.len, int(duration(src)))
    print("2/3 finding best moments...")
    if a.start:
        plan = [(st, None, None) for st in a.start]
    else:
        plan = [(st, None, None) for st in find_moments(src, a.top, clip_len)]
        if a.ai and not a.no_captions and clip_len < duration(src):
            plan = ai_plan(src, a, clip_len) or plan
    print("   starts (s):", [round(p[0]) for p in plan])
    for n, (st, words, hooks) in enumerate(plan, 1):
        make_clip(src, st, clip_len, od, f"clip_{n:02d}", a, words, hooks)
    print(f"\nAll clips in: {od}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"ffmpeg failed:\n{e.stderr.decode()[-1500:] if e.stderr else e}")
