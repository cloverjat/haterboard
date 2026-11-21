"""TikTok posting via the official Content Posting API (Direct Post).

Requirements:
  * A TikTok developer app with the Content Posting API product + `video.publish` scope.
  * Until TikTok audits your app, posts are forced to SELF_ONLY (private) visibility.
  * `is_aigc: true` labels the post as AI-generated content (TikTok requires this for
    realistic AI content; we always set it).

Token: the refresh token from TikTok Login Kit (valid 365 days). Run
`python -m autopilot auth-tiktok` once to obtain it.
"""
from __future__ import annotations

import http.server
import secrets
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

from ..config import env

API = "https://open.tiktokapis.com/v2"
MB = 1024 * 1024


def access_token() -> str:
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token", "refresh_token": env("TIKTOK_REFRESH_TOKEN"),
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"TikTok token refresh failed: {data}")
    if data.get("refresh_token") and data["refresh_token"] != env("TIKTOK_REFRESH_TOKEN"):
        print("[tiktok] NOTE: TikTok issued a new refresh token; update TIKTOK_REFRESH_TOKEN:",
              data["refresh_token"][:12] + "...")
    return data["access_token"]


def _chunks(size: int) -> tuple[int, int]:
    """TikTok rules: chunks 5-64MB, last chunk may be up to 128MB; files <5MB = 1 chunk."""
    if size <= 64 * MB:
        return size, 1
    chunk = 10 * MB
    return chunk, size // chunk  # remainder is merged into the final chunk


def upload(cfg: dict, video: Path, caption: str) -> dict:
    tok = access_token()
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}

    info = requests.post(f"{API}/post/publish/creator_info/query/", headers=h, timeout=30).json()
    allowed = info.get("data", {}).get("privacy_level_options", [])
    privacy = cfg["publish"]["tiktok"].get("privacy", "SELF_ONLY")
    if allowed and privacy not in allowed:
        privacy = "SELF_ONLY" if "SELF_ONLY" in allowed else allowed[0]

    size = video.stat().st_size
    chunk, count = _chunks(size)
    init = requests.post(f"{API}/post/publish/video/init/", headers=h, json={
        "post_info": {
            "title": caption[:2200],
            "privacy_level": privacy,
            "disable_duet": False, "disable_comment": False, "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
            "is_aigc": True,
        },
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk, "total_chunk_count": count},
    }, timeout=60).json()
    if init.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init failed: {init['error']}")
    publish_id = init["data"]["publish_id"]
    upload_url = init["data"]["upload_url"]

    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            body = f.read(end - start + 1)
            r = requests.put(upload_url, data=body, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            }, timeout=600)
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"TikTok chunk {i} upload failed: {r.status_code} {r.text[:300]}")

    status = {}
    for _ in range(40):
        time.sleep(6)
        status = requests.post(f"{API}/post/publish/status/fetch/", headers=h,
                               json={"publish_id": publish_id}, timeout=30).json().get("data", {})
        if status.get("status") in ("PUBLISH_COMPLETE", "FAILED"):
            break
    if status.get("status") == "FAILED":
        raise RuntimeError(f"TikTok publish failed: {status.get('fail_reason')}")
    post_ids = status.get("publicaly_available_post_id") or []
    return {"platform": "tiktok", "id": str(post_ids[0]) if post_ids else publish_id,
            "publish_id": publish_id, "status": status.get("status"), "privacy": privacy}


def interactive_auth(port: int = 8766) -> None:
    """One-time Login Kit flow. Register http://127.0.0.1:8766/callback/ as a redirect URI
    (TikTok desktop/web apps) - or use your own HTTPS redirect and paste the `code` manually."""
    key, secret = env("TIKTOK_CLIENT_KEY"), env("TIKTOK_CLIENT_SECRET")
    redirect = f"http://127.0.0.1:{port}/callback/"
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": key, "scope": "user.info.basic,video.publish,video.upload,video.list",
        "response_type": "code", "redirect_uri": redirect, "state": state,
    })
    box: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                box["code"] = q.get("code", [""])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorized. You can close this tab.")

        def log_message(self, *a):
            pass

    print("Open this URL and approve access:\n", url)
    webbrowser.open(url)
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    while "code" not in box:
        srv.handle_request()
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": key, "client_secret": secret, "code": box["code"],
        "grant_type": "authorization_code", "redirect_uri": redirect,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    r.raise_for_status()
    print("\nTIKTOK_REFRESH_TOKEN=" + r.json()["refresh_token"])
