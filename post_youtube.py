#!/usr/bin/env python3
"""Upload clips to YouTube Shorts (free YouTube Data API).

First time: put your OAuth client file at ./client_secret.json (Google Cloud ->
APIs & Services -> enable "YouTube Data API v3" -> Credentials -> OAuth client ID ->
Desktop app). A browser window asks you to log in once; token.json is saved.

Usage:
  python post_youtube.py out/<name>/clip_01.json            # uploads as PRIVATE
  python post_youtube.py out/<name>/*.json --public          # public (needs verified API project)
Quota: ~6 uploads/day on the free 10,000-unit quota.
"""
import argparse, json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
HERE = Path(__file__).parent


def creds():
    tok = HERE / "token.json"
    c = Credentials.from_authorized_user_file(tok, SCOPES) if tok.exists() else None
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
    if not c or not c.valid:
        c = InstalledAppFlow.from_client_secrets_file(HERE / "client_secret.json", SCOPES).run_local_server(port=0)
    tok.write_text(c.to_json())
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", help="clip_XX.json files made by clip.py")
    ap.add_argument("--public", action="store_true")
    a = ap.parse_args()
    yt = build("youtube", "v3", credentials=creds())
    for j in a.clips:
        meta = json.loads(Path(j).read_text())
        video = Path(j).parent / meta["file"]
        body = {
            "snippet": {"title": meta["title"][:100], "description": meta["caption"],
                        "tags": ["GTA6", "GTA VI", "gaming", "shorts"], "categoryId": "20"},
            "status": {"privacyStatus": "public" if a.public else "private",
                       "selfDeclaredMadeForKids": False},
        }
        req = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=MediaFileUpload(str(video), resumable=True))
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
        print(f"uploaded {video.name}: https://youtube.com/shorts/{resp['id']} ({body['status']['privacyStatus']})")


if __name__ == "__main__":
    main()
