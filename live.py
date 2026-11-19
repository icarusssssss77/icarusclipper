#!/usr/bin/env python3
"""Icarus Live Clipper: watch a live stream, auto-clip hype moments as they happen.

Usage:
  python live.py twitch.tv/CHANNEL --credit "🎥 @CHANNEL"            # Twitch (chat + audio)
  python live.py "https://www.youtube.com/watch?v=LIVE_ID"          # YouTube/Kick (audio only)
  python live.py test.mp4 --test                                     # replay a file as if live
  add --post-youtube to upload each clip to YouTube Shorts as PRIVATE.

How: streamlink records the stream into 10 s chunks (ffmpeg segment). Every chunk is scored
per second: loudness jump vs. the last 2 min + Twitch chat burst (msgs/sec vs. baseline, with
hype words like LUL / OMG / clip / W). A spike -> cut ~30 s around it -> clip.py's 9:16 + captions.
Recording/chat approach adapted from PeakCut (MIT). Only clip streams you have permission for.
"""
import argparse, re, socket, ssl, subprocess, sys, threading, time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import clip

SEG = 10           # seconds per recorded chunk
KEEP = 600         # keep the last 10 min of chunks on disk
HYPE = re.compile(r"\b(lul|lmao+|omg+|clip+|w+|holy|kekw|pog\w*|no way|bro+|wtf|💀|😂)\b", re.I)


class Chat:
    """Anonymous Twitch chat reader: counts messages per second (hype words count x2)."""
    def __init__(self, channel, t0):
        self.t0, self.counts, self.channel = t0, {}, channel.lower()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=30)
                s = ssl.create_default_context().wrap_socket(raw, server_hostname="irc.chat.twitch.tv")
                s.sendall(f"NICK justinfan{int(time.time()) % 90000 + 10000}\r\nJOIN #{self.channel}\r\n".encode())
                buf = ""
                print(f"   chat: connected to #{self.channel}")
                while True:
                    data = s.recv(4096).decode("utf-8", "ignore")
                    if not data:
                        break
                    buf += data
                    *lines, buf = buf.split("\r\n")
                    for ln in lines:
                        if ln.startswith("PING"):
                            s.sendall(b"PONG :tmi.twitch.tv\r\n")
                        elif "PRIVMSG" in ln:
                            sec = int(time.time() - self.t0)
                            self.counts[sec] = self.counts.get(sec, 0) + (2 if HYPE.search(ln.split(":", 2)[-1]) else 1)
            except Exception as e:
                print(f"   chat: {e}; retrying in 10 s")
                time.sleep(10)

    def series(self, n):
        return np.array([self.counts.get(i, 0) for i in range(n)], dtype=np.float32)


def recorder(source, buf, test):
    """Start recording into buf/seg_XXXXX.ts. Returns the process."""
    seg = ["-c", "copy", "-f", "segment", "-segment_time", str(SEG), "-reset_timestamps", "1",
           "-segment_format", "mpegts", "-segment_list", str(buf / "list.csv"), "-segment_list_type", "csv",
           str(buf / "seg_%05d.ts")]
    if test:   # replay a local file at real speed, re-encoded so chunks cut cleanly
        cmd = ["ffmpeg", "-v", "error", "-re", "-i", source, "-c:v", "libx264", "-preset", "ultrafast",
               "-g", "60", "-c:a", "aac"] + seg[2:]
        return subprocess.Popen(cmd)
    sl = subprocess.Popen(["streamlink", "--stdout", source, "best"],
                          stdout=subprocess.PIPE)
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-i", "pipe:0"] + seg, stdin=sl.stdout)
    return ff


def done_segments(buf):
    """Finished chunks from ffmpeg's list: [(path, start, end)] on the stream clock."""
    lst = buf / "list.csv"
    if not lst.exists():
        return []
    out, t = [], 0.0
    for row in lst.read_text().splitlines():
        name, _, _ = row.split(",")[:3]
        d = clip.duration(buf / name) if (buf / name).exists() else SEG
        out.append((buf / name, t, t + d)); t += d
    return out


def loud_per_sec(path):
    sr = 8000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    n = len(a) // sr
    return list(20 * np.log10(np.sqrt((a[: n * sr].reshape(n, sr) ** 2).mean(1) + 1e-9))) if n else []


def z(x, i, win=5, base=120):
    """How far the last `win` s at i stand above the `base` s before them (z-score)."""
    if i < 30:
        return 0.0
    ref = x[max(0, i - base):i - win]
    return float((x[i - win:i].mean() - ref.mean()) / (ref.std() + 1e-6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="twitch.tv/name, a live URL, or a file with --test")
    ap.add_argument("--test", action="store_true", help="replay a local file as if live")
    ap.add_argument("--len", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=3.0, help="spike score to clip (lower = more clips)")
    ap.add_argument("--cooldown", type=int, default=90, help="min seconds between clips")
    ap.add_argument("--max-clips", type=int, default=20)
    ap.add_argument("--credit", default="")
    ap.add_argument("--model", default="small")
    ap.add_argument("--mode", choices=["blur", "crop"], default="blur")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--no-ai", dest="ai", action="store_false", help="skip Claude hooks")
    ap.add_argument("--post-youtube", action="store_true", help="upload each clip as PRIVATE")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    name = re.sub(r"\W+", "_", a.source.split("/")[-1])[:40] or "live"
    od = Path(a.out) / f"live_{name}_{time.strftime('%m%d_%H%M')}"; buf = od / "_buffer"
    buf.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rec = recorder(a.source, buf, a.test)
    m = re.search(r"twitch\.tv/(\w+)", a.source)
    chat = Chat(m.group(1), t0) if m and not a.test else None
    print(f"Watching {a.source} -> clips in {od}  (Ctrl+C to stop)")

    loud, loud_done, scored, pending, last_clip, n = [], [], 0, [], -1e9, 0
    opts = SimpleNamespace(no_captions=a.no_captions, model=a.model, credit=a.credit, mode=a.mode, source=a.source, ai=a.ai)
    try:
        while n < a.max_clips:
            time.sleep(2)
            segs = done_segments(buf)
            alive = rec.poll() is None
            # ffmpeg only lists a chunk once it is finished, so every listed chunk is complete
            for p, s, e in segs[len(loud_done):]:
                sec = loud_per_sec(p) if p.exists() else []
                need = int(round(e)) - len(loud)
                loud += (sec + [sec[-1] if sec else -90.0] * need)[:max(need, 0)]
                loud_done.append(p)
            L = np.array(loud, dtype=np.float32)
            C = chat.series(len(L)) if chat else None
            # score each new second; the event happened just before the spike
            for i in range(scored, len(L)):
                score = z(L, i) + (z(C, i) if C is not None else 0)
                if score >= a.threshold and i - last_clip >= a.cooldown:
                    st = max(0, i - int(a.len * 0.6))
                    pending.append(st); last_clip = i
                    print(f"⚡ spike at {i}s (score {score:.1f}) -> clip {st}-{st + a.len}s")
            scored = len(L)
            # cut pending clips once their chunks are on disk
            stream_end = segs[-1][2] if segs else 0
            for st in [p for p in pending if p + a.len + 2 <= stream_end or not alive]:
                pending.remove(st); n += 1
                parts = [s for s in segs if s[2] > st and s[1] < st + a.len and s[0].exists()]
                if not parts:
                    continue
                lst = buf / f"cat_{n}.txt"
                lst.write_text("".join(f"file '{p[0].resolve()}'\n" for p in parts))
                joined = buf / f"cat_{n}.ts"
                clip.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
                meta = clip.make_clip(joined, st - parts[0][1], a.len, od, f"live_{n:02d}", opts)
                joined.unlink(); lst.unlink()
                if a.post_youtube:
                    subprocess.run([sys.executable, str(Path(__file__).parent / "post_youtube.py"), str(meta)])
            # drop old chunks
            for p, s, e in segs:
                if e < stream_end - KEEP and p.exists():
                    p.unlink()
            if not alive and not pending:
                print("Stream ended.")
                break
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        rec.terminate()
    print(f"{n} clips in {od}")


if __name__ == "__main__":
    main()
