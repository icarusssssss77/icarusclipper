# Borrowed from PeakCut (MIT)

Source: https://github.com/haziqahmedqasmi/PeakCut @ 1bef2b4. License kept in `LICENSE`.
Inspected by The Homework (NEO LVIDEUR): CAUTION leaning SAFE. Copied, never run.
Fills the gaps from the opensource-clipping parts: live streams + non-transcript moment signals.

## What's here
- `studio/live.py`: live clipping for Twitch / Kick / YouTube, channel auto-watcher, auto-post.
- `studio/brain.py`: moment judging: loudness spikes (+60% over a 3-min baseline, `loud_zscore`),
  unique-chatter bursts (`judge_signals`), per-game rules (`GAME_RULES`); LLM only on spikes.
- `studio/games.py`: game tags incl. GTA VI.
- `studio/facecam.py` + `studio/render.py`: gameplay + facecam vertical layout.
- `studio/accounts.py`: YouTube / Instagram / TikTok posting (stores OAuth refresh tokens: keep them
  out of git, in env or a secrets store).
- Helpers they import: `ai, config, roman, media, ctx, transcribe, safe`. `GAMING.md`: author's notes.

## Left out on purpose (multi-user SaaS parts)
auth, admin, mailer, server, db, updates (polls GitHub every minute), web/, deploy/.
`live.py` still imports some left-out modules (alerts, auth, creators, jobs, load, profiles, tools,
usage): stub or remove those imports when wiring it in. `render.py` expects the `studio/fonts/`
folder (not copied, grab from source if needed). ASR model (0.5-1 GB) downloads on first run.

## Known gap
No visual / kill-feed detection: silent gameplay with no chat or loudness spike is missed.
Get streamer permission before posting their clips.
