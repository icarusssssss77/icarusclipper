"""Instagram Reels via the Instagram Graph API (resumable upload, no public URL needed).

Requirements: an Instagram Business or Creator account linked to a Facebook
Page, a Meta developer app with instagram_basic + instagram_content_publish,
and a long-lived access token. Put IG_USER_ID and IG_ACCESS_TOKEN in .env.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def upload(video: Path, meta: dict, cfg: dict) -> str:
    user, token = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if not user or not token:
        raise RuntimeError("IG_USER_ID / IG_ACCESS_TOKEN missing in .env")
    caption = meta["caption"] + "\n\n" + " ".join(f"#{t}" for t in meta["hashtags"])

    # 1) create a container that expects a resumable upload
    c = requests.post(f"{GRAPH}/{user}/media", timeout=30, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
        "share_to_feed": "true", "access_token": token,
    }).json()
    if "id" not in c:
        raise RuntimeError(f"IG container failed: {c}")
    cid, upload_uri = c["id"], c["uri"]

    # 2) push the bytes
    size = video.stat().st_size
    with open(video, "rb") as f:
        r = requests.post(upload_uri, data=f, timeout=600, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
        })
    if r.status_code >= 300:
        raise RuntimeError(f"IG upload failed: {r.status_code} {r.text}")

    # 3) wait for Instagram to process it
    for _ in range(60):
        s = requests.get(f"{GRAPH}/{cid}", timeout=30,
                         params={"fields": "status_code,status", "access_token": token}).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"IG processing failed: {s}")
        time.sleep(5)
    else:
        raise RuntimeError("IG processing timed out")

    # 4) publish
    p = requests.post(f"{GRAPH}/{user}/media_publish", timeout=30,
                      data={"creation_id": cid, "access_token": token}).json()
    if "id" not in p:
        raise RuntimeError(f"IG publish failed: {p}")
    return f"instagram media id {p['id']}"
