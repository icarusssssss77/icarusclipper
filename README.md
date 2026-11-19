# GTA 6 auto-clipper (free, runs in the cloud)

Watches Twitch streams 24/7, finds the moments, cuts 9:16 Shorts with word-by-word captions
and 3 hook variants, has Gemini **watch** each clip and approve or reject it, then posts the
approved ones to YouTube Shorts / TikTok / Reels, spaced out within daily caps. Everything is free.

```
live Twitch channels (up to 5 at once)
  -> signals: loudness, chat bursts, motion, scene cuts, HUD changes; ad breaks skipped
  -> Whisper transcript -> Gemini picks the exact cut + writes hooks -> hook filter keeps 3
  -> render v1/v2/v3.mp4 (1080x1920, captions, hook banner)
  -> Gemini watches it: approve (score >= 7) / reject, picks the best hook
  -> poster: best approved clip every 90 min, max 6/day on YouTube
  -> files auto-deleted after a day
```

## 1. Accounts (you do these)

- **Google account** (for YouTube + Gemini + Google Cloud): create the YouTube channel on it.
- **Gemini key**: https://aistudio.google.com/apikey -> Create API key -> put in `.env`
  (`cp .env.example .env`, paste after `GEMINI_API_KEY=`).
- **YouTube upload access**: Google Cloud Console -> new project -> enable *YouTube Data API v3* ->
  OAuth consent screen (External, add yourself as test user) -> Credentials -> OAuth client ID
  (*Desktop app*) -> download JSON to `secrets/youtube_client_secret.json`. Then on the Mac:
  `.venv/bin/python -m clipper auth youtube` (opens the browser once; the token is copied to the server).
- **TikTok** (Outlook account): developers.tiktok.com app with Content Posting API + Login Kit,
  redirect `http://localhost:8765/callback`, keys in `.env`, then `.venv/bin/python -m clipper auth tiktok`
  on the Mac. Add `"tiktok"` to `[upload] platforms` in config.toml.
  Until TikTok audits the app, its posts are private.

## 2. Oracle Cloud server (free forever)

1. Sign up at https://www.oracle.com/cloud/free/ (card needed for verification, not charged).
   Pick a home region near you; if it later says "out of capacity", try another availability domain.
2. Create instance: **Compute -> Instances -> Create**
   - Image: **Ubuntu 24.04** (or 22.04)
   - Shape: **Ampere -> VM.Standard.A1.Flex, 4 OCPU, 24 GB RAM** (Always Free)
   - SSH keys: **Paste public key** -> contents of `~/.ssh/clipper_oracle.pub` on this Mac
   - Boot volume: 100 GB is fine (200 GB free total)
3. Copy the instance's **Public IP**, then from the Mac:
   ```
   deploy/push.sh <public-ip>
   ```
   This uploads the code + `.env` + `secrets/`, installs everything, and starts the clipper as a
   service that restarts itself and survives reboots. Re-run it after any change.

Watch it: `ssh -i ~/.ssh/clipper_oracle ubuntu@<ip> journalctl -u clipper -f`
Status:   `ssh -i ~/.ssh/clipper_oracle ubuntu@<ip> 'cd Clipping && .venv/bin/python -m clipper status'`

## Commands (on the server or the Mac)

```
python -m clipper live                 # what the service runs
python -m clipper status               # pending / approved / posted / rejected + AI reasons
python -m clipper vod <url-or-file>    # clip a VOD (auto-reviewed too)
python -m clipper approve <id> --variant 2   # force-post a clip yourself
python -m clipper post                 # post the next due clip now
```

## Settings worth knowing (config.toml)

- `channels`, `max_live_recordings` (5): who to watch and how many at once.
- `[auto] min_score` (7): raise for stricter AI approval.
- `[safety] daily_caps`, `min_minutes_between_posts`: posting pace. YouTube's free API quota is ~6/day.
- `[storage]`: how long files are kept. Clips live on YouTube after posting, not on the server.
- `layout`: `blur-fit` (default). `auto` = facecam stack when one is detected (check results).
- `hud_region`: where GTA 6 shows wanted stars; adjust once you see footage.

## Know before you post

- Only clip streamers who allow it or run clipping campaigns; channels that reupload without
  permission get copyright strikes.
- New YouTube API projects may have uploads locked private until Google's audit.
- Captions are English-only (`small.en`). Live chat signal is Twitch only.
- Never commit or share `.env` / `secrets/`.
