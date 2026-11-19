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


def transcribe(path, model):
    from faster_whisper import WhisperModel
    m = WhisperModel(model, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(str(path), word_timestamps=True, vad_filter=True)
    return [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or []) if w.word.strip()]


def ts(t):
    h, r = divmod(max(t, 0), 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(words, path, clip_len, credit):
    """Big centered word-group captions (3 words at a time), TikTok style."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial Black,96,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Credit,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,0,8,40,40,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if credit:
        lines.append(f"Dialogue: 0,{ts(0)},{ts(clip_len)},Credit,,0,0,0,,{credit}")
    for i in range(0, len(words), 3):
        g = words[i:i + 3]
        start, end = g[0][0], g[-1][1]
        if i + 3 < len(words):
            end = min(max(end, start + 0.3), words[i + 3][0])
        text = " ".join(w for _, _, w in g).upper().replace("{", "").replace("}", "")
        # \pos puts captions in the lower-middle of the frame, under the gameplay
        lines.append(f"Dialogue: 1,{ts(start)},{ts(end)},Cap,,0,0,0,,{{\\pos({W//2},{int(H*0.72)})}}{text}")
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


def caption_text(words, credit):
    said = " ".join(w for _, _, w in words)
    hook = re.split(r"(?<=[.!?])\s", said.strip())[0][:80] if said else "GTA 6 moment"
    title = f"{hook} #Shorts"
    body = f"{hook}\n\n{('Credit: ' + credit) if credit else ''}\n{HASHTAGS}".strip()
    return title, body


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
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    out_root = Path(a.out); dl = out_root / "_downloads"; dl.mkdir(parents=True, exist_ok=True)
    print("1/4 getting video..."); src = download(a.source, dl)
    name = re.sub(r"\W+", "_", src.stem)[:40]; od = out_root / name; od.mkdir(exist_ok=True)
    clip_len = min(a.len, int(duration(src)))
    print("2/4 finding best moments..."); starts = a.start or find_moments(src, a.top, clip_len)
    print("   starts (s):", starts)
    for n, st in enumerate(starts, 1):
        tag = f"clip_{n:02d}"; raw = od / f"{tag}_raw.wav"
        words = []
        if not a.no_captions:
            print(f"3/4 [{tag}] transcribing...")
            run(["ffmpeg", "-y", "-ss", str(st), "-t", str(clip_len), "-i", str(src),
                 "-vn", "-ac", "1", "-ar", "16000", str(raw)])
            words = transcribe(raw, a.model); raw.unlink()
        ass = od / f"{tag}.ass"; write_ass(words, ass, clip_len, a.credit)
        print(f"4/4 [{tag}] rendering vertical clip...")
        render(src, st, clip_len, ass, od / f"{tag}.mp4", a.mode)
        title, body = caption_text(words, a.credit)
        (od / f"{tag}.json").write_text(json.dumps(
            {"file": f"{tag}.mp4", "source": a.source, "start": st, "title": title, "caption": body},
            indent=2))
        (od / f"{tag}.txt").write_text(f"{title}\n\n{body}\n")
        print(f"   done -> {od / (tag + '.mp4')}")
    print(f"\nAll clips in: {od}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"ffmpeg failed:\n{e.stderr.decode()[-1500:] if e.stderr else e}")
