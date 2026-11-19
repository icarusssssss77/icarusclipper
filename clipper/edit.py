"""One ffmpeg pass: cut -> 9:16 layout -> hook banner -> word captions -> loudnorm."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def credit_png(text: str, cfg: dict, out: Path) -> Path:
    """Small always-on '@streamer' credit, white with dark outline."""
    W = cfg["edit"]["width"]
    font = ImageFont.truetype(cfg["captions"]["font_path"], 38)
    img = Image.new("RGBA", (W, 70), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tw = d.textlength(text, font=font)
    d.text(((W - tw) / 2, 12), text, font=font, fill="#FFFFFF", stroke_width=4, stroke_fill="#000000")
    img.save(out)
    return out


def hook_png(text: str, cfg: dict, out: Path) -> Path:
    h, c = cfg["hook"], cfg["captions"]
    W = cfg["edit"]["width"]
    font = ImageFont.truetype(c["font_path"], h["font_size"])
    lines = textwrap.wrap(text, width=18) or [text]
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = [probe.textlength(l, font=font) for l in lines]
    asc, desc = font.getmetrics()
    line_h = asc + desc + 6
    pad_x, pad_y = 36, 22
    bw = int(min(max(widths) + 2 * pad_x, W - 60))
    bh = int(line_h * len(lines) + 2 * pad_y)
    img = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0 = (W - bw) // 2
    d.rounded_rectangle([x0, 0, x0 + bw, bh], radius=26, fill=h["bg_color"])
    for i, (l, lw) in enumerate(zip(lines, widths)):
        d.text(((W - lw) / 2, pad_y + i * line_h), l, font=font, fill=h["text_color"])
    img.save(out)
    return out


def _layout(cfg: dict, facecam) -> tuple[str, int]:
    """Returns (filtergraph producing [v0], y-centre for the hook banner)."""
    e = cfg["edit"]
    W, H = e["width"], e["height"]
    mode = e["layout"]
    if mode == "auto":   # full-screen on phones: face on top if there is one, else zoomed gameplay
        mode = "facecam-stack" if facecam else "center-crop"
    if mode == "facecam-stack" and facecam:
        cx, cy, cw, ch = facecam
        cam_h = int(H * 0.36) // 2 * 2
        game_h = H - cam_h
        g = (
            f"[0:v]split=2[a][b];"
            f"[a]crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f},"
            f"scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h},setsar=1[cam];"
            f"[b]crop='min(iw,ih*{W}/{game_h})':ih,scale={W}:{game_h},setsar=1[game];"
            f"[cam][game]vstack[v0]"
        )
        return g, cam_h
    if mode == "center-crop":
        return f"[0:v]crop='min(iw,ih*9/16)':ih,scale={W}:{H},setsar=1[v0]", 260
    fg_h = W * 9 // 16
    top = (H - fg_h) // 2 - 160
    g = (
        f"[0:v]split=2[a][b];"
        f"[a]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,"
        f"crop={W // 4}:{H // 4},boxblur=10:2,scale={W}:{H},setsar=1[bg];"
        f"[b]scale={W}:-2,setsar=1[fg];"
        f"[bg][fg]overlay=(W-w)/2:{top}[v0]"
    )
    return g, max(top // 2, 120)


def thumbnail(src: Path, t: float, cfg: dict, facecam, text: str, out: Path, raw: bool = False) -> Path:
    """Clean full-screen frame at time t (no captions) + big yellow hook text.
    raw=True: src is an already-rendered vertical clip, use its frame as is."""
    graph, hook_y = ("[0:v]null[v0]", 260) if raw else _layout(cfg, facecam)
    png = out.with_suffix(".png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(src),
                    "-filter_complex", graph, "-map", "[v0]", "-frames:v", "1", "-update", "1", str(png)],
                   check=True)
    if not png.exists():   # retry once with fast seek after input (some .ts segments start mid-GOP)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-ss", f"{t:.2f}",
                        "-filter_complex", graph, "-map", "[v0]", "-frames:v", "1", "-update", "1", str(png)],
                       check=True)
    img = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(img)
    W = img.width
    lines = textwrap.wrap(text.upper(), width=12) or [text.upper()]   # 2-3 short, huge lines
    size = 150
    while True:
        font = ImageFont.truetype(cfg["captions"]["font_path"], size)
        if max(d.textlength(l, font=font) for l in lines) <= W - 70 or size <= 70:
            break
        size -= 6
    asc, desc = font.getmetrics()
    lh = asc + desc + 4
    y = max(40, hook_y - lh * len(lines) // 2)
    for i, l in enumerate(lines):
        lw = d.textlength(l, font=font)
        d.text(((W - lw) / 2, y + i * lh), l, font=font, fill="#FFE600", stroke_width=12, stroke_fill="#000000")
    img.save(out, "JPEG", quality=88)
    png.unlink(missing_ok=True)
    return out


def render(src: Path, start: float, duration: float, out: Path, cfg: dict,
           captions: tuple[Path, int, int] | None, hook: Path | None, facecam=None,
           credit: Path | None = None) -> Path:
    graph, hook_y = _layout(cfg, facecam)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src)]
    last, idx = "v0", 1
    if hook:
        cmd += ["-loop", "1", "-i", str(hook)]
        hh = Image.open(hook).height
        secs = cfg["hook"].get("seconds", 0)
        when = f":enable='lt(t,{secs})'" if secs else ""
        graph += f";[{idx}:v]format=rgba[hk];[{last}][hk]overlay=0:{hook_y - hh // 2}:shortest=1{when}[vh]"
        last, idx = "vh", idx + 1
    if credit:
        cmd += ["-loop", "1", "-i", str(credit)]
        graph += f";[{idx}:v]format=rgba[cr];[{last}][cr]overlay=0:{cfg['edit']['height'] - 260}:shortest=1[vr]"
        last, idx = "vr", idx + 1
    if captions:
        listing, _band_h, y = captions
        cmd += ["-f", "concat", "-safe", "0", "-i", str(listing)]
        graph += f";[{idx}:v]format=rgba[cap];[{last}][cap]overlay=0:{y}:format=auto[vc]"
        last = "vc"
    cmd += [
        "-filter_complex", graph, "-map", f"[{last}]", "-map", "0:a:0?",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg["edit"]["crf"]), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out),
    ]
    subprocess.run(cmd, check=True)
    return out
