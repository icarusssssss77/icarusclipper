"""AI moment picking + hooks using your own Claude plan (`claude -p`), no extra API cost.

Falls back silently (returns None) if the claude CLI is missing or answers badly,
so the pipeline always still works on loudness alone.
"""
import json, re, shutil, subprocess

HOOK_RULES = """Hook rules (from data on 3,481 gaming Shorts):
- 2-6 words, sentence case, NEVER ALL CAPS.
- Best structures: number promise ("3 seconds of pure chaos"), shock fact ("He survived a 200ft fall"),
  relatable ("Me on my first GTA 6 mission"), withheld/negation ("Don't skip the ending").
- Avoid vague ("This is crazy"), announcements ("New GTA 6 clip"), clickbait lies.
- The 3 hooks must use 3 DIFFERENT structures and match what is actually said/shown."""

BAD = re.compile(r"^(this is (crazy|insane|wild)|new gta|check (this|out)|watch this)", re.I)


def _ask(prompt, timeout=180):
    if not shutil.which("claude"):
        return None
    try:
        out = subprocess.run(["claude", "-p", "--model", "sonnet", prompt],
                             capture_output=True, text=True, timeout=timeout).stdout
        m = re.search(r"\{.*\}", out, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def clean_hooks(hooks):
    """Gate: drop ALL CAPS / vague / too long hooks."""
    good = []
    for h in hooks or []:
        h = str(h).strip().strip('"')
        letters = re.sub(r"[^A-Za-z]", "", h)
        if not h or (letters and letters.isupper() and len(letters) > 3) or BAD.search(h) or len(h.split()) > 8:
            continue
        good.append(h)
    return good


def pick_moments(candidates, n, clip_len, title=""):
    """candidates: [(start_sec, end_sec, transcript_text)]. Returns [(start, [hooks])] or None."""
    listing = "\n".join(f"[{i}] {s:.0f}s-{e:.0f}s: {t[:1500] or '(no speech, loud moment)'}"
                        for i, (s, e, t) in enumerate(candidates))
    prompt = f"""You pick the most viral moments from a GTA 6 stream/video{f' titled "{title}"' if title else ''} for {clip_len}-second vertical Shorts.
Candidate windows (absolute seconds) with what was said:
{listing}

Pick the best {n}. For each, choose a start second inside its window so the {clip_len}s clip opens on the
reaction/build-up and ENDS on the payoff. Prefer: funny reactions, fails, chaos, surprises, big wins.
{HOOK_RULES}

Answer ONLY with JSON: {{"clips":[{{"start":123,"why":"short reason","hooks":["...","...","..."]}}]}}"""
    r = _ask(prompt)
    if not r or not isinstance(r.get("clips"), list):
        return None
    lo, hi = min(c[0] for c in candidates), max(c[1] for c in candidates)
    out = []
    for c in r["clips"][:n]:
        try:
            st = float(c["start"])
        except Exception:
            continue
        if lo <= st <= hi:                      # reject made-up timestamps
            out.append((st, clean_hooks(c.get("hooks")), str(c.get("why", ""))[:120]))
    return out or None


def hooks_for(transcript, clip_len):
    """3 hooks for one clip's transcript, or None."""
    prompt = f"""Write 3 hooks for a {clip_len}-second GTA 6 vertical Short. What is said in it:
"{transcript[:2000] or '(no speech: gameplay moment)'}"
{HOOK_RULES}
Answer ONLY with JSON: {{"hooks":["...","...","..."]}}"""
    r = _ask(prompt, timeout=90)
    h = clean_hooks(r.get("hooks")) if r else []
    return h or None
