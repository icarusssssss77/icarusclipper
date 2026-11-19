# Icarus Clipper

Long stream/video -> best moments -> vertical 9:16 shorts with big captions -> YouTube Shorts.
All free: yt-dlp, ffmpeg, faster-whisper (Whisper models from Hugging Face), YouTube Data API.

## Mac setup (once, ~5 min)
```bash
brew install ffmpeg python@3.12
cd ~/icarus-clipper
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Make clips
```bash
source .venv/bin/activate
python clip.py "https://www.youtube.com/watch?v=VIDEO_ID" --top 3 --len 30 --credit "🎥 @streamer"
open out/
```
- `--model base` = faster, `--model small` (default) = better captions.
- `--start 1830 --start 4410` = cut exact moments (seconds) instead of auto-pick.
- `--mode crop` = fill the screen instead of blurred background.
- Each clip gets `clip_XX.mp4` + `clip_XX.txt` (title + caption + hashtags to paste).

## Post
- **YouTube Shorts (auto):** set up `client_secret.json` (see top of post_youtube.py), then
  `python post_youtube.py out/<name>/clip_01.json` -> uploads PRIVATE; check it, then make public.
  Unverified API projects can only post private; ~6 uploads/day free.
- **TikTok / Instagram Reels:** upload `clip_XX.mp4` + paste `clip_XX.txt` from your phone
  (AirDrop the out/ folder), or schedule with a free tier of Buffer / Metricool.

## Permission rule
Only clip streams where you're in the creator's clipping program or have their OK.
