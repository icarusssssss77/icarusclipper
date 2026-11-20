"""Phone notifications through ntfy (https://ntfy.sh). Free, no account.

Set NTFY_TOPIC (a GitHub Actions secret, or a line in .env) to a hard-to-guess topic name and
subscribe to the same topic in the ntfy app. Anyone who knows the topic can read it, so it is
never written in this (public) repository. Without NTFY_TOPIC nothing is sent.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)


def send(title: str, message: str, click: str | None = None, tags: list[str] | None = None,
         priority: int = 3) -> None:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    body = {"topic": topic, "title": title[:200], "message": message[:1000], "priority": priority}
    if click:
        body["click"] = click
    if tags:
        body["tags"] = tags
    try:
        requests.post(os.environ.get("NTFY_SERVER", "https://ntfy.sh"), json=body, timeout=15).raise_for_status()
    except Exception as e:   # a notification must never break a run
        log.warning("ntfy notification failed: %s", str(e)[:120])
