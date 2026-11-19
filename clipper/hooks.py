"""Hook gate. Hooks are the on-screen line that opens each variant.

What wins (3,481 gaming Shorts): number promise 2.46x, shock fact 1.68x,
relatable 1.48x, withheld/negation 1.41x. What loses: ALL CAPS 0.90x,
announcement 0.85x, vague 0.67x. Hooks are 2-6 words.
"""
from __future__ import annotations

import re

STRUCTURES = ["number_promise", "shock_fact", "relatable", "withheld_negation"]

VAGUE = re.compile(
    r"\b(you won'?t believe|wait for it|watch (this|till|until)|this is (crazy|insane|wild)|"
    r"(crazy|insane|wild|epic|funny|best) moments?|must see|omg|bruh|no way|unbelievable)\b",
    re.I,
)
ANNOUNCE = re.compile(
    r"^(new|introducing|announcing|breaking|update|official|just in)\b|"
    r"\b(is (here|out)|just dropped|out now|coming soon|now available|launch(es|ed)?)\b",
    re.I,
)


def reject_reason(hook: str) -> str | None:
    h = hook.strip()
    words = h.split()
    if not 2 <= len(words) <= 6:
        return "must be 2-6 words"
    letters = [c for c in h if c.isalpha()]
    if len(letters) > 4 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return "ALL CAPS"
    if VAGUE.search(h):
        return "vague"
    if ANNOUNCE.search(h):
        return "announcement wording"
    return None


def pick(hooks: list[dict], n: int = 3) -> list[dict]:
    """Keep passing hooks, preferring distinct structures, up to n."""
    ok = [h for h in hooks if h.get("text") and not reject_reason(h["text"])]
    chosen, seen = [], set()
    for h in ok:
        if h.get("structure") not in seen:
            chosen.append(h)
            seen.add(h.get("structure"))
    for h in ok:
        if len(chosen) >= n:
            break
        if h not in chosen:
            chosen.append(h)
    return chosen[:n]
