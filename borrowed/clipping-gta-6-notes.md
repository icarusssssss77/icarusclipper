# Notes from clipping-gta-6: GTA Shorts hook research and clipper ideas

- Source: https://github.com/R3LAMP4GO/clipping-gta-6
- Commit: bde439394c291577a7f5151e35a81fbea61ce440
- AGPL: ideas only, no code copied. Everything below is paraphrased facts, numbers and patterns.
- Read on 2026-11-19 as untrusted data; nothing was run or installed.

Link base (B): https://github.com/R3LAMP4GO/clipping-gta-6/blob/bde439394c291577a7f5151e35a81fbea61ce440/
All links below are B + path.

---

## 1. What goes viral in GTA Shorts (market facts)

Source: [research/viral-gta-shorts.md](B/research/viral-gta-shorts.md), raw sample in
[research/viral-gta-shorts-data.md](B/research/viral-gta-shorts-data.md).

The sample is 28 creator Shorts with 500k to 51M views (collected 2026-11-09). Top four formats:

| Format | Length | Fact | Example |
|---|---|---|---|
| Streamer reaction (split screen, face on top, game below) | 9-25s | No hook banner, 1-word captions on the seam, the face is the hook | Kai Cenat "Actually Thinks That A GTA VI Character Is Indecisive" (6.8M) |
| News / "did you know" list | 50-60s | Huge caps hook pinned for the whole clip, then numbered beats | MrBossFTW "Kids WON'T Be Able To Play GTA 6!" (51M), "4 NEW Features..." (10M) |
| Creator facecam over gameplay | 9-18s | Small series label, boxed facecam, one-joke punchline | DarkViperAU "We Are THAT Close - GTA 6 News" (1.3M) |
| Skit | 45-90s | White box hook at top, payoff at the end | RDCworld1 "There has to be a reason for this game taking this long" (5M) |

Lines worth stealing as rules ([viral-gta-shorts.md L14-L21](B/research/viral-gta-shorts.md#L14-L21)):
- Hooks are 2-6 words (all 13 sample hooks under 7; relatable scenes may reach 9).
- Pin the hook for the full clip; first spoken words repeat it; no "hey guys" intros.
- One coloured keyword in the hook.
- Reaction clips skip the banner entirely.
- None of the 28 opened on filler. Spoken-open mix: in-scene cold open 7, claim/news 5, action 4, question 4, number promise 3, setup tease 2 ([L40-L49](B/research/viral-gta-shorts.md#L40-L49)).
- Captions: about 8-10% of frame height, 1-3 words at a time, bold white with black outline, key word yellow or red, a different colour per speaker when voices overlap ([L67-L71](B/research/viral-gta-shorts.md#L67-L71)).
- Length: reactions 9-25s, info up to about 58s, avoid 60-90s unless it is a skit.

### Fonts seen on top performers ([L80-L91](B/research/viral-gta-shorts.md#L80-L91))
Montserrat Black caps for news hooks (MrBossFTW), Bebas Neue on black box for reactions (Kai), TikTok Sans Bold on white box for skits, TikTok Sans SemiBold with a purple keyword for DarkViper, a comic outline font for playful gameplay. All open licences.

### Title patterns ([L54-L65](B/research/viral-gta-shorts.md#L54-L65))
- Name + "Actually" + surprise + emoji for streamer clips ("xQc Actually Robbed A Bank For This").
- Negation shock, number listicle, CAPS question ("Cost HOW MUCH!?"), curiosity ("What Happens If You Shoot The Moon In GTA 6?"), withheld ending with "...".
- 35-70 characters is the sweet spot (max 100), 1-2 caps words, emoji at the end for comedy only, "GTA 6" in the title, 2-4 hashtags.

## 2. Measured effects on 3,481 gaming Shorts

Source: [viral-gta-shorts.md L153-L179](B/research/viral-gta-shorts.md#L153-L179) and the dataset
[research/gaming-shorts-titles.json](B/research/gaming-shorts-titles.json).

Dataset facts: 3,481 titles, 19 channels, niches gta 1,081 / cod 1,400 / other 600 / zombies 400. Each row holds channel, title, views and "lift" (views vs the channel's own recent norm, log scale). So channel size cancels out.

Views multiplier by title feature (90% range in brackets):

| Feature | x | Note |
|---|---|---|
| number promise | 2.46 (1.49-4.12) | only 27 Shorts, rests mostly on MrBossFTW |
| shock fact | 1.68 | 22 Shorts |
| relatable situation | 1.48 | 88 |
| withheld / negation | 1.41 | 73 |
| question | 1.24 | 129 |
| names a streamer | 1.21 | 153, all gaming |
| tease | 1.17 | 185 |
| superlative | 1.14 | 285 |
| premise + twist, first-person claim | 0.97 / 0.94 | no effect |
| ALL CAPS | 0.90 | drop |
| announcement wording ("update", "patch") | 0.85 | drop |
| vague | 0.67 | drop |

Frame review (75 frames, first 1.2s of each channel's best and worst Shorts): winners show a face mid-reaction about 80% of the time vs about 60% for losers, plus one complete specific line on screen. Losers open on dark or empty establishing shots or a single mid-sentence caption word. Famous guests are the biggest outliers (one clip hit 119x its channel norm).

Honest caveat from the authors: these are title effects used as a proxy for on-screen hooks; they rank hooks, they do not forecast views.

### Outlier study ([L121-L151](B/research/viral-gta-shorts.md#L121-L151))
14 streamer outliers (12-117x channel norm). Shared traits worth using as a checklist:
1. Premise lands in one second.
2. Title states the situation, withholds the outcome ("Wanted To Prank", "Caught Me").
3. One trigger per clip: curiosity gap, viewer as judge, play-along streak, suspense, irony, shock confession, status, absurd one-liner.
4. The face is the payoff; most end on the reaction so the loop restarts.
5. 8-15s when the trigger is simple.
6. Silent clips use action captions (`*ENTERS*`, `*GETS CLOSER*`).
7. Emoji matches the feeling.
8. No lie: the clip must deliver the twist or it is spam-policy clickbait.

### Zylok teardown and survey ([L181 onward](B/research/viral-gta-shorts.md#L181))
- Best clips end on the result, not on the decision or a take. Weak clips ended on choices.
- Cold open on the first meaningful word.
- Swear censoring by masking a vowel (F*CK) while audio stays untouched.
- From 25 clips: one-word captions plus action labels 25/25; colour or white flash 76%; sub-bass boom off a cut 56% (about 1 per 19s, max 3 per clip); music only about 20%; zero camera shake, zero freeze frames (so skip those).
- Practical rule they derived: boom on the payoff and the 1-2 biggest reactions (at most 1 per 4s), flash on the payoff, punch-in zoom on shouted lines, music only over 2s+ speech-free stretches, nothing on clips already loud.
- Meme-game music is Content ID claimable. They gate music behind explicit approval and list CC0 mood tracks from OpenGameArt instead ([L260 onward](B/research/viral-gta-shorts.md#L260)).

## 3. How hooks are checked (algorithm, own words)

Source: [clipper/hooks.py](B/clipper/hooks.py).

Hook check is a rule engine, no AI:
1. Count words (GTA 6 counts as one). Fail if under 2 or over 8 (9 for relatable situation).
2. Detect which of nine structures the hook matches using keyword and pattern tests: question, tease, withheld/negation, number promise, shock fact, first-person claim, relatable situation, premise + twist (a shouted caps word besides a few names), superlative ([L12-L45 area](B/clipper/hooks.py#L10-L50)).
3. Fail "vague": the hook has at most one content word after removing a stoplist. Fail bare labels: no structure and 4 words or fewer. Fail plain statements: no structure at all. Fail labelling words like "reaction", "compilation", "highlights".
4. Notes (not fails): first-person alone, caps-twist alone.
5. Title check: max 100 chars, no more than 2 caps words, not all caps, warn on announcement words, must mention the topic (or carry the hashtag).
6. Pair check: each hook's title should share a structure with its hook.
7. Playbook check: each clip type has two lead structures; warn if the hooks used skip both.
8. Variety: with 3+ hooks, need at least 3 distinct structures so the A/B test tests something.
9. Edit checks on the clip itself: opens on filler in first 1.5s, dead air of 2s+ with no word or label, 3s+ speech gap with no music decision, hook that repeats a word from the last 3s (spoiler check), labels must be 1-3 words and inside the clip, 60s cap even for multi-segment cuts ([L177 onward](B/clipper/hooks.py#L177)).

Opening-line classifier uses the same idea for the spoken first line: filler, action, in-scene, question, number, claim, setup tease ([L30-L55](B/clipper/hooks.py#L30-L55)).

## 4. How hooks are ranked (simulator)

Source: [clipper/simulate.py](B/clipper/simulate.py).

Algorithm in plain words:
1. Turn every title in the dataset into a set of features (the structures above plus "names a streamer", "vague", "all caps", "announcement").
2. Effect of a feature = average lift of titles that have it minus average lift of titles that lack it, per scope. Needs at least 10 examples, else effect is 0.
3. Bootstrap: resample the rows 200 times to get a 90% range per feature. Scope is chosen narrowly: own uploads first (once they exist), then the GTA niche if it is conclusive (n at least 15 and range excludes 1x), else all gaming.
4. Score a hook = its single strongest structure effect plus the modifier effects (streamer name, vague, caps, announcement). Taking the max not the sum avoids counting overlapping ideas twice.
5. Run the simulation: each round re-samples effects, scores every hook, records the winner. Output is expected multiplier, 90% range, win share, and a "keep top 3 with different types" line ([L148-L175](B/clipper/simulate.py#L148-L175)).
6. Strategy simulator ([strategies](B/clipper/simulate.py)): at a fixed upload budget (8), compares "one hook per clip", "all types", "best 2/3/4 that fit". Per-channel effects are shrunk toward zero when few channels back them. Result they report: best 3 fitting types per clip, 6% average shortfall vs 23% for one hook per clip and 17% for forcing every type including misfits.
7. Feedback loop idea: once your own uploads have 48h of data, they get added to the dataset and take priority.

## 5. Candidate selection

Source: [clipper/candidates.py](B/clipper/candidates.py), [clipper/signals.py](B/clipper/signals.py), score assembly in [clipper/analyze.py L150-L215](B/clipper/analyze.py#L150-L215).

- Per-second signals: loudness (ffmpeg ebur128), "jump" (how far a second rises above the median of the previous 8s, with a floor at normal talking level so speech after silence is not a jump), YouTube "most replayed" heatmap, hype-keyword and loud-sound-event hits, speech rate. Weighted sum from config; if no heatmap, its weight is shared among the others.
- Windows: smooth the score, take local peaks, cut a window around each peak (40% before, 60% after the target length), snap start and end to sentence boundaries, drop windows overlapping more than 30%, rank by half peak plus half mean of top 30% of seconds.
- Clip type guess: reaction (loudness spread of 7 LU or more, loud events, title says react/live, or 2+ hype words per minute) gets 22s target; else info with 45s target.
- Tier: strong needs score 45+ and evidence (jump 8 LU, 2 hype words, a sound event or heat 0.6); maybe needs 30+ and weaker evidence; recommended count = strong plus half the maybes, capped at one per 3 minutes.
- Candidate count is about one per 2.5 minutes of source, between 4 and 25.
- Gem: "scenario windows" start on transcript cues like "let me show you", "first time", "I just built", "try this" and run until a 6s pause. These catch quiet curiosity-gap clips that loudness misses ([candidates.py scenario cues](B/clipper/candidates.py)).
- Each candidate also gets a contact sheet image so the AI judges visually.

## 6. Twitch ad slate detection

Source: [clipper/signals.py ad_mask](B/clipper/signals.py#L96-L124).

Idea, no AI and cheap:
- Sample 1 frame per second, shrink to 32x18 pixels.
- A frame is an ad slate if the blue channel average is clearly above red (about 1.8x) and green (about 1.6x) AND the frame is almost flat (mean neighbour pixel difference under about 13). It is the "commercial in progress" flat blue-purple screen.
- Smooth: fill 1-2s holes inside a break, then delete runs shorter than 5s.
- Used by setting those seconds' score to 0 and removing words spoken in them, then trimming picks off the ad edges ([analyze.py L172-L174](B/clipper/analyze.py#L172-L174)).
- Only applied to live recordings.
- Weakness to remember: thresholds were tuned to one slate look; check other platforms (Kick, YouTube have different breaks).

## 7. Profile: GTA 6 topic setup

Source: [profiles/gta6/profile.yaml](B/profiles/gta6/profile.yaml), [creators.yaml](B/profiles/gta6/creators.yaml), [live.yaml](B/profiles/gta6/live.yaml).

Facts:
- Topic keywords: gta 6, gta vi, grand theft auto, vice city, leonida, rockstar, nopixel, rp, heist, trailer.
- Hashtags: #gta6 #gtavi #shorts.
- Topic gate: title or description or tags must say GTA 6 / VI / #gta6 / Leonida. Exclude titles about GTA 5/IV/Online, Red Dead, NoPixel, "waiting for GTA 6", memes.
- Extra searches: "GTA 6 reaction", "GTA 6 gameplay funny".
- Watched creators: GTA Series Videos, MrBossFTW, DarkViperAU, xQc, Kai Cenat, VanossGaming, Typical Gamer. Live: xQc (Twitch and Kick), Kai Cenat (Twitch and YouTube), all "topic only" (record only while on topic).
- Caption fixes (whisper mistakes to correct as whole words): Trevor, Michael, Franklin, Lamar, Lester, Lucia, Leonida get their wrong spellings mapped (e.g. "trever", "lusia", "leonidas").
- Vocabulary idea: feed a short list of proper names (Lucia, Jason, Leonida, Vice City, Trevor, Michael, Franklin, Lester, Lamar) to the speech recogniser as its initial prompt so it spells names right up front; keep a fix map as the backup layer. Cheap and worth copying.
- Preferences ([prefs.yaml](B/prefs.yaml)): hooks per video 5 (research says 3 is best), 2 new sources per day, only the first 90 min of long streams analysed.

## 8. Live recorder and health check

Source: [clipper/live.py](B/clipper/live.py).

- Recorder: probe the channel with a yt-dlp metadata call (live or not; Twitch title lives in description). If live, get the HLS URL, then ffmpeg stream-copy into 30-minute segments with reset timestamps (no re-encode, no gap). Each finished chunk becomes a normal job; the newest segment is skipped until done writing.
- Gapless restart: the new recorder starts first, and only once it is writing does it kill the old one by pid.
- If the stream session drops, fetch a fresh HLS URL straight away without re-probing. Gives up after 3 failed probes a minute apart.
- Pid-file claim prevents two recorders for one stream; a cap on max recorders with priority order.
- Health check (empty means all good): live on-topic stream not being recorded; recorder running but no new .ts file for 10 minutes (stuck); a chunk whose analysis failed 3 times; free disk below a configured GB. Each issue carries the fix command in its message.
- Stranded jobs (analysis killed by a restart) are re-queued on every watch tick.
- A separate cleanup tool deletes old source video so disks do not fill.

## 9. Other gems

- Multi-streamer edit and story cut ([viral-gta-shorts.md L73-L78](B/research/viral-gta-shorts.md#L73-L78)): join several beats of one stream, or the same cutscene from several streams. Cutscene dialogue is identical across streams, so a transcript search finds every copy ([live.py find](B/clipper/live.py#L446)). Rule: no footage used twice, 3s tolerance; credit each streamer. Reason: reused-content policy and no reach for repeats.
- Voice separation ([clipper/speakers.py](B/clipper/speakers.py)): demucs two-stem split into vocals and game audio; diarisation assigns speakers to words so overlapping voices can get different caption colours.
- AI voiceover rule ([L93-L96](B/research/viral-gta-shorts.md#L93-L96)): add one line (10 words max) only for silent gameplay, trailers, news or mid-conversation starts; skip it on reactions; never narrate over the payoff.
- Dub ([clipper/dub.py](B/clipper/dub.py)): re-render a clip in another language with a cloned voice per speaker (external TTS), speed-up cap about 1.35x, pitch and loudness matched, AI disclosure line and creator credit added in the description. Ethics point: they always disclose.
- Hook count insight: 3 variants of different structure per clip beats 1 or 7.

---

## 10. Build ourselves: visual detection for silent gameplay

The seed finds moments from sound, words and the replay heatmap only. It has no visual signal at all (a search for scene or frame analysis found nothing in the analysis path). A GTA gameplay clipper with no commentary needs one. Plan, all cheap CPU:

1. Scene-cut density. Run ffmpeg scene detection on the source (threshold about 0.3-0.4, they used 0.35 in their survey) and count cuts per 5s window. High density marks action or editor-made montage; flat zero over 20s marks driving or menus. Use as a score input and as a "skip" filter.
2. Frame-diff motion energy. Sample 4-5 fps at 160x90 grayscale, mean absolute difference between frames, smoothed. Spikes mean explosions, crashes, camera whips. Combine with audio loudness jump (they already do) and require both for a "strong" tier on silent footage.
3. Kill-feed / event region watch. Fix a crop for the HUD region (top-right in GTA-style games; calibrate once per game with one screenshot). Two methods, start with the simple one:
   - Region diff: per-frame change inside only that crop. A new line appearing makes a short sharp spike while the rest of the screen may be calm. Count spikes per 10s.
   - Template match: save 3-5 small icons or text-strip templates (wanted stars flashing, "WASTED", "MISSION PASSED", kill banner), run OpenCV matchTemplate on the crop at 2 fps with a threshold of about 0.8. Each hit becomes a timestamped event like their loud-sound events (weight 1.5).
4. Wanted-level and screen-state cues: red/blue flashing hue in the lower or whole frame, WASTED text (dark desaturated frame plus red text), fade to black. Cheap colour histograms at 1 fps.
5. Face-cam presence (for streams): is there a big face region and does it jump in size or brightness (reaction) in a 1s window. Their research says winners show a face mid-reaction in about 80% of first frames, so score first-frame quality of each candidate: face present, not dark, not empty establishing shot.
6. Use the output: add `visual_score` next to loudness in window scoring, store hits in the candidate json, and show them on the contact sheet. Silent clips then get action-label captions (`*CRASHES*`, `*WASTED*`) from the detected event name, a trick the seed's research shows works for silent winners.
7. Validate before trusting: hand-label 20 clips from a GTA stream, measure how many top-5 windows per source hit a real moment, with and without the visual score. Keep only if it beats audio-only.

Also build: ad-slate mask for Twitch recordings (idea in section 6, our own thresholds on our own samples), a hook linter with the structure list and word limits (section 3), and our own title-effect dataset from our channels so the simulator ranks on our niche, not theirs.
