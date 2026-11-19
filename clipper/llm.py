"""Free cloud LLMs, tried in order from config.toml [ai] providers.

  gemini  free key: https://aistudio.google.com/apikey  -> GEMINI_API_KEY   (first choice)
  groq    free key: https://console.groq.com/keys       -> GROQ_API_KEY     (backup when Gemini rate-limits)

If none works, the pipeline still runs with rule-based cuts and template hooks.
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)


def _gemini(model: str, system: str, user: str) -> str:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=180,
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
        },
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _groq(model: str, system: str, user: str) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions", timeout=180,
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        json={"model": model, "temperature": 0.7, "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


PROVIDERS = {"gemini": (_gemini, "GEMINI_API_KEY"), "groq": (_groq, "GROQ_API_KEY")}


def ask_json(cfg: dict, system: str, user: str) -> dict | None:
    for name in cfg["ai"]["providers"]:
        fn, env = PROVIDERS[name]
        if not os.environ.get(env):
            continue
        try:
            return _parse(fn(cfg["ai"]["models"][name], system, user))
        except Exception as e:  # rate limit, bad JSON, network: try the next one
            log.warning("%s failed (%s), trying next", name, e)
    log.warning("no AI provider available - using rule-based cuts and hooks")
    return None


def watch_video(cfg: dict, video_bytes: bytes, prompt: str) -> dict | None:
    """Gemini watches a small mp4 and answers in JSON. Only Gemini can see video."""
    import base64

    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['ai']['models']['gemini']}:generateContent",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=300,
            json={
                "contents": [{"role": "user", "parts": [
                    {"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(video_bytes).decode()}},
                    {"text": prompt},
                ]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
            },
        )
        r.raise_for_status()
        return _parse(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as e:
        log.warning("Gemini video review failed: %s", e)
        return None


def _parse(text: str) -> dict:
    text = re.sub(r"```(json)?", "", text).strip()
    return json.loads(text[text.find("{"): text.rfind("}") + 1])
