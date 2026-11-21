"""YouTube Shorts upload via the official Data API v3 (resumable upload).

A video <= 3 min with a vertical aspect ratio is classified as a Short automatically.
Every upload sets `containsSyntheticMedia: true` - YouTube's required disclosure for
AI-generated/altered content.
"""
from __future__ import annotations

import http.server
import json
import urllib.parse
import webbrowser
from pathlib import Path

import requests

from ..config import env

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def access_token() -> str:
    r = requests.post(TOKEN_URL, data={
        "client_id": env("YOUTUBE_CLIENT_ID"), "client_secret": env("YOUTUBE_CLIENT_SECRET"),
        "refresh_token": env("YOUTUBE_REFRESH_TOKEN"), "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def upload(cfg: dict, video: Path, title: str, description: str, tags: list[str]) -> dict:
    yt = cfg["publish"]["youtube"]
    tok = access_token()
    title = title[:95] + (" #Shorts" if "#shorts" not in title.lower() else "")
    meta = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:30],
            "categoryId": yt.get("category_id", "24"),
            "defaultLanguage": cfg["channel"].get("language", "en"),
        },
        "status": {
            "privacyStatus": yt.get("privacy", "public"),
            "selfDeclaredMadeForKids": bool(yt.get("made_for_kids", False)),
            "containsSyntheticMedia": True,
        },
    }
    size = video.stat().st_size
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        data=json.dumps(meta), timeout=60,
    )
    init.raise_for_status()
    with open(video, "rb") as f:
        up = requests.put(init.headers["Location"], data=f,
                          headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4",
                                   "Content-Length": str(size)}, timeout=1800)
    up.raise_for_status()
    vid = up.json()["id"]
    return {"platform": "youtube", "id": vid, "url": f"https://youtube.com/shorts/{vid}"}


def stats(video_ids: list[str]) -> dict[str, dict]:
    if not video_ids:
        return {}
    tok = access_token()
    out = {}
    for i in range(0, len(video_ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                         params={"part": "statistics", "id": ",".join(video_ids[i:i + 50])},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        r.raise_for_status()
        for it in r.json().get("items", []):
            s = it["statistics"]
            out[it["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                             "comments": int(s.get("commentCount", 0))}
    return out


def interactive_auth(port: int = 8765) -> None:
    """One-time: opens Google consent screen and prints a refresh token for .env / GitHub secrets.

    In Google Cloud Console create an OAuth client of type "Desktop app" and enable
    "YouTube Data API v3". Desktop clients accept any http://127.0.0.1:<port> redirect.
    """
    cid, secret = env("YOUTUBE_CLIENT_ID"), env("YOUTUBE_CLIENT_SECRET")
    redirect = f"http://127.0.0.1:{port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent",
    })
    code_box: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code_box["code"] = q.get("code", [""])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorized. You can close this tab.")

        def log_message(self, *a):
            pass

    print("Open this URL and approve access:\n", url)
    webbrowser.open(url)
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    while "code" not in code_box:
        srv.handle_request()
    r = requests.post(TOKEN_URL, data={
        "code": code_box["code"], "client_id": cid, "client_secret": secret,
        "redirect_uri": redirect, "grant_type": "authorization_code",
    }, timeout=30)
    r.raise_for_status()
    print("\nYOUTUBE_REFRESH_TOKEN=" + r.json()["refresh_token"])
