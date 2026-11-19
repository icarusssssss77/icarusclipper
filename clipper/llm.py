"""Free cloud LLMs, tried in order from config.toml [ai] providers.

  gemini  free key: https://aistudio.google.com/apikey  -> GEMINI_API_KEY   (first choice)
  groq    free key: https://console.groq.com/keys       -> GROQ_API_KEY     (backup when Gemini rate-limits)

Gemini walks its model list in order: a busy (503), rate-limited (429) or retired (404)
model falls through to the next. If nothing works, the pipeline still runs with
rule-based cuts and template hooks, and nothing is auto-posted.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time

import requests

log = logging.getLogger(__name__)
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
SKIP = {402, 404, 429, 500, 503, 504}   # 402 = paid-only model on a free key


def _models(cfg: dict) -> list[str]:
    m = cfg["ai"]["models"]["gemini"]
    return [m] if isinstance(m, str) else list(m)


def _gemini_call(cfg: dict, parts: list[dict], system: str | None, temperature: float, timeout: int) -> dict:
    """Returns the parsed JSON answer. A model that is busy/unavailable OR answers with broken JSON
    is skipped in favour of the next model in the list."""
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    last = None
    for model in _models(cfg):
        for attempt in range(2):
            try:
                r = requests.post(GEMINI_URL.format(model), json=body, timeout=timeout,
                                  headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            except requests.RequestException as e:
                last = f"{model}: {e}"
                break
            if r.ok:
                try:
                    cand = r.json()["candidates"][0]["content"]["parts"]
                    text = "".join(p.get("text", "") for p in cand if not p.get("thought"))
                    answer = _parse(text)
                except (KeyError, IndexError, ValueError) as e:
                    last = f"{model}: unusable answer ({e})"
                    log.warning("gemini %s gave an unusable answer, trying next model", model)
                    break
                log.debug("gemini answered with %s", model)
                return answer
            last = f"{model}: HTTP {r.status_code}"
            if r.status_code == 503 and attempt == 0:
                time.sleep(4)          # brief spike: one quick retry on the same model
                continue
            if r.status_code in SKIP:
                break                  # try the next model
            r.raise_for_status()       # 400/401/403: bad request or bad key, stop here
    raise RuntimeError(f"all Gemini models unavailable (last: {last})")


def _groq(cfg: dict, system: str, user: str) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions", timeout=180,
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        json={"model": cfg["ai"]["models"]["groq"], "temperature": 0.7,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini_text(cfg: dict, system: str, user: str) -> dict:
    return _gemini_call(cfg, [{"text": user}], system, 0.7, 120)


PROVIDERS = {"gemini": (_gemini_text, "GEMINI_API_KEY"), "groq": (_groq, "GROQ_API_KEY")}


def ask_json(cfg: dict, system: str, user: str) -> dict | None:
    for name in cfg["ai"]["providers"]:
        fn, env = PROVIDERS[name]
        if not os.environ.get(env):
            continue
        try:
            out = fn(cfg, system, user)
            return out if isinstance(out, dict) else _parse(out)
        except Exception as e:  # rate limit, bad JSON, network: try the next provider
            log.warning("%s failed (%s), trying next", name, e)
    log.warning("no AI provider available - using rule-based cuts and hooks")
    return None


def watch_media(cfg: dict, data: bytes, mime: str, prompt: str) -> dict | None:
    """Gemini looks at a video (video/mp4) or image (image/jpeg) and answers in JSON."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    parts = [{"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
             {"text": prompt}]
    try:
        return _gemini_call(cfg, parts, None, 0.2, 90)
    except Exception as e:
        log.warning("Gemini %s look failed: %s", mime, e)
        return None


def watch_video(cfg: dict, video_bytes: bytes, prompt: str) -> dict | None:
    return watch_media(cfg, video_bytes, "video/mp4", prompt)


def _parse(text: str) -> dict:
    """First JSON object in the text (ignores code fences and anything after the object)."""
    text = re.sub(r"```(json)?", "", text).strip()
    obj, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    if not isinstance(obj, dict):
        raise ValueError("answer is not a JSON object")
    return obj
