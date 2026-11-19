"""TikTok via the Content Posting API (Direct Post, file upload).

Setup: developers.tiktok.com -> create app -> add "Content Posting API" +
"Login Kit", scopes user.info.basic + video.publish, redirect URI
http://localhost:8765/callback. Put TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET
in .env, then run:  python -m clipper auth tiktok

NOTE: until TikTok audits your app, every post is forced to private (SELF_ONLY).
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

from ..config import ROOT

API = "https://open.tiktokapis.com/v2"
TOKEN_FILE = ROOT / "secrets" / "tiktok_token.json"
REDIRECT = "http://localhost:8765/callback"


def _save(tok: dict) -> dict:
    tok["expires_at"] = time.time() + tok.get("expires_in", 0) - 60
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok))
    return tok


def _token_request(data: dict) -> dict:
    data |= {"client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"]}
    r = requests.post(f"{API}/oauth/token/", data=data, timeout=30)
    r.raise_for_status()
    tok = r.json()
    if "access_token" not in tok:
        raise RuntimeError(f"TikTok token error: {tok}")
    return _save(tok)


def authorize() -> None:
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "response_type": "code",
        "scope": "user.info.basic,video.publish", "redirect_uri": REDIRECT, "state": state,
    })
    got: dict = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"TikTok connected. You can close this tab.")

        def log_message(self, *a):
            pass

    print("Opening TikTok login in your browser...")
    webbrowser.open(url)
    HTTPServer(("localhost", 8765), H).handle_request()
    if got.get("state") != state or "code" not in got:
        raise RuntimeError(f"TikTok auth failed: {got}")
    _token_request({"code": got["code"], "grant_type": "authorization_code", "redirect_uri": REDIRECT})
    print("TikTok authorized.")


def _access_token() -> str:
    if not TOKEN_FILE.exists():
        raise RuntimeError("TikTok not authorized - run: python -m clipper auth tiktok")
    tok = json.loads(TOKEN_FILE.read_text())
    if time.time() > tok["expires_at"]:
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    return tok["access_token"]


def upload(video: Path, meta: dict, cfg: dict) -> str:
    headers = {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json; charset=UTF-8"}
    size = video.stat().st_size
    chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
    n_chunks = max(1, size // chunk)
    title = f"{meta['title']} " + " ".join(f"#{t}" for t in meta["hashtags"])
    init = requests.post(f"{API}/post/publish/video/init/", headers=headers, timeout=30, json={
        "post_info": {"title": title[:2200], "privacy_level": "SELF_ONLY",
                      "disable_comment": False, "disable_duet": False, "disable_stitch": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk, "total_chunk_count": n_chunks},
    }).json()
    if init.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok init failed: {init}")
    upload_url, publish_id = init["data"]["upload_url"], init["data"]["publish_id"]

    with open(video, "rb") as f:
        for i in range(n_chunks):
            start = i * chunk
            end = size - 1 if i == n_chunks - 1 else start + chunk - 1
            f.seek(start)
            data = f.read(end - start + 1)
            r = requests.put(upload_url, data=data, timeout=300, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            })
            r.raise_for_status()
    return f"tiktok publish_id={publish_id} (posted as private until your app is audited)"
