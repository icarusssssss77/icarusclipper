"""YouTube Shorts via the YouTube Data API v3.

Setup: Google Cloud project -> enable "YouTube Data API v3" -> OAuth client ID
(type "Desktop app") -> download JSON to secrets/youtube_client_secret.json.
Then run:  python -m clipper auth youtube
"""
from __future__ import annotations

from pathlib import Path

from ..config import ROOT

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
SECRETS = ROOT / "secrets"


def _creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token = SECRETS / "youtube_token.json"
    secret = SECRETS / "youtube_client_secret.json"
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not secret.exists():
            raise RuntimeError(f"missing {secret} - see clipper/uploaders/youtube.py")
        creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
    SECRETS.mkdir(exist_ok=True)
    token.write_text(creds.to_json())
    return creds


def authorize() -> None:
    _creds()
    print("YouTube authorized.")


def upload(video: Path, meta: dict, cfg: dict) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=_creds())
    tags = meta["hashtags"]
    body = {
        "snippet": {
            "title": meta["title"][:95] + " #Shorts" if "#shorts" not in meta["title"].lower() else meta["title"][:100],
            "description": meta["caption"] + "\n\n" + " ".join(f"#{t}" for t in tags),
            "tags": tags,
            "categoryId": "20",  # Gaming
        },
        "status": {
            "privacyStatus": cfg["upload"]["youtube_privacy"],
            "selfDeclaredMadeForKids": False,
        },
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return f"https://youtube.com/shorts/{resp['id']}"
