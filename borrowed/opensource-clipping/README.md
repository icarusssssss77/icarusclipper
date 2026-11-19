# Borrowed from opensource-clipping (MIT)

Source: https://github.com/NaufalRizqullah/opensource-clipping @ cc1d78c. License kept in `LICENSE`.
Inspected by The Homework (NEO LVIDEUR): CAUTION, no malware found. Copied, never run.

## What's here and why
- `clipping/studio/`: 9:16 reframe + styled Whisper captions. For GTA gameplay use a
  center crop or blurred-background layout, not face tracking.
- `clipping/providers/`: LLM picks moments, returns JSON, timestamps validated.
- `clipping/config.py`: settings the above import.
- `youtube_uploader/`, `facebook_uploader/`, `upload_safety.json`: scheduled Shorts/Reels
  with caps (1 per run, 2 per day, manual approval).

## Left out on purpose
Notebooks (`curl | sh` installer), Web Studio (public ngrok tunnel holding API keys),
unpinned heavy requirements. Pin your own deps; imports may need adjusting.

## Not covered: live streams
The seed only clips finished videos. Live plan: streamlink records ~2 min chunks
(ffmpeg segment) -> detect hype from chat bursts, audio peaks, Twitch viewer clips ->
cut ~30 s around each spike -> studio/ reframe + captions -> uploader.
Get streamer permission before posting.
