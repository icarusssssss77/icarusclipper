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


def authorize(remote: bool = False, finish: str | None = None) -> None:
    """Local: opens a browser here. Remote (2 steps, the channel owner approves on THEIR device,
    no password ever reaches this machine):
      python -m clipper auth youtube --remote            -> prints a link to send them
      python -m clipper auth youtube --finish "<url>"    -> the address they send back
    """
    if not remote and not finish:
        _creds()
        print("YouTube authorized.")
        return
    import json
    import os

    from google_auth_oauthlib.flow import InstalledAppFlow

    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # redirect is plain http://localhost
    secret = SECRETS / "youtube_client_secret.json"
    pending = SECRETS / "youtube_pending.json"
    if not secret.exists():
        raise SystemExit(f"missing {secret} - put the downloaded OAuth JSON there first")
    redirect = "http://localhost:8765/"
    if not finish:
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES, redirect_uri=redirect)
        url, state = flow.authorization_url(access_type="offline", prompt="consent")
        pending.write_text(json.dumps({"state": state, "code_verifier": flow.code_verifier}))
        pending.chmod(0o600)
        print(url)
        return
    if not pending.exists():
        raise SystemExit("run `auth youtube --remote` first")
    p = json.loads(pending.read_text())
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES, redirect_uri=redirect,
                                                     state=p["state"], code_verifier=p["code_verifier"])
    flow.fetch_token(authorization_response=finish.strip())
    (SECRETS / "youtube_token.json").write_text(flow.credentials.to_json())
    (SECRETS / "youtube_token.json").chmod(0o600)
    pending.unlink()
    print("YouTube authorized. Token saved to secrets/youtube_token.json")


def upload(video: Path, meta: dict, cfg: dict) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=_creds())
    tags = meta["hashtags"]
    # Vertical + under 3 min is a Short automatically; no #Shorts needed. The first 3 hashtags
    # in the description (#GTA6 #GTAVI #GTA) show above the title.
    search_tags = list(dict.fromkeys(tags + ["GTA 6", "GTA VI", "Grand Theft Auto 6", "GTA 6 gameplay",
                                             "GTA 6 clips", "Vice City", meta.get("channel", "")]))
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["caption"].strip() + "\n\n" + " ".join(f"#{t}" for t in tags),
            "tags": [t for t in search_tags if t][:30],
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
    thumb = video.parent / "thumb.jpg"
    if thumb.exists():
        try:  # needs a phone-verified channel; a failure here never fails the upload
            yt.thumbnails().set(videoId=resp["id"], media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("thumbnail not set (%s) - verify the channel at youtube.com/verify", e)
    return f"https://youtube.com/shorts/{resp['id']}"
