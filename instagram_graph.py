"""Official Instagram Graph API publisher (page-linked Business account).

Instagram's official API requires the video at a PUBLIC url, so we host each
clip on catbox.moe (free, no account) first, then:
  POST /{ig_id}/media            -> creation container
  GET  /{creation_id}?fields=status_code -> poll until FINISHED
  POST /{ig_id}/media_publish    -> go live

Token: .env INSTAGRAM_GRAPH_TOKEN (long-lived Facebook user token, page-linked)
IG id: .env INSTAGRAM_IG_ID (Instagram Business account id)
Host:  graph.facebook.com  (the user token parses here; graph.instagram.com rejects it)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

API = "https://graph.facebook.com/v21.0"
REEL_MAX_SECONDS = 90


def _token() -> str:
    t = os.environ.get("INSTAGRAM_GRAPH_TOKEN", "")
    if not t:
        raise RuntimeError("INSTAGRAM_GRAPH_TOKEN missing in .env")
    return t


def get_ig_user_id() -> str:
    ig = os.environ.get("INSTAGRAM_IG_ID")
    if ig:
        return ig
    # resolve via the linked Facebook page (may be flaky; prefer INSTAGRAM_IG_ID)
    accts = requests.get(f"{API}/me/accounts", params={"access_token": _token()},
                         timeout=30).json().get("data", [])
    for page in accts:
        r = requests.get(f"{API}/{page['id']}",
                         params={"fields": "instagram_business_account",
                                 "access_token": page["access_token"]}, timeout=30).json()
        iba = r.get("instagram_business_account")
        if iba:
            return iba["id"]
    raise RuntimeError("Could not resolve Instagram Business account id")


def _transcode(path: str) -> str:
    """Re-encode to Instagram-safe H.264/AAC (IG rejects AV1/VP9).

    Returns a path to a temp .mp4 (new file). If already H.264 it is still
    normalized for safety (faststart, yuv420p).
    """
    import subprocess
    ff = str(Path(__file__).resolve().parent / "bin" / "ffmpeg.exe")
    out = str(Path(path).with_suffix("")) + "_ig.mp4"
    subprocess.run([ff, "-y", "-i", path,
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                           "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", out],
                   check=True, capture_output=True, timeout=600)
    return out


def _host_public(video_path: str) -> str:
    """Upload to uguu.se, return a public https url Instagram can fetch.

    Instagram's Graph API needs the media at a public URL it can download
    during container creation. uguu.se serves the raw file with a video/*
    content-type (tmpfiles wraps it in HTML; catbox is Cloudflare-blocked),
    which is what Meta's fetcher requires.
    """
    with open(video_path, "rb") as f:
        r = requests.post("https://uguu.se/upload.php?output=text",
                          files={"files[]": f}, timeout=180)
    r.raise_for_status()
    url = r.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"uguu upload failed: {url}")
    return url


def _create_container(ig_id: str, video_url: str, caption: str, is_reel: bool) -> str:
    r = requests.post(f"{API}/{ig_id}/media",
                      data={"caption": caption, "video_url": video_url,
                            "media_type": "REELS" if is_reel else "VIDEO",
                            "access_token": _token()}, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def _wait_finished(creation_id: str) -> None:
    for _ in range(40):
        r = requests.get(f"{API}/{creation_id}",
                         params={"fields": "status_code", "access_token": _token()},
                         timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"poll GET {r.status_code}: {r.text[:400]}")
        j = r.json()
        code = j.get("status_code", "")
        if code == "FINISHED":
            return
        if code == "ERROR":
            full = requests.get(f"{API}/{creation_id}",
                                params={"access_token": _token()}, timeout=30).text
            raise RuntimeError(f"Instagram rejected container. Detail: {full[:400]}")
        time.sleep(10)
    raise RuntimeError("Timed out waiting for Instagram to process video")


def publish(video_path: str, caption: str, duration: int = 0) -> str:
    ig_id = get_ig_user_id()
    safe = _transcode(video_path)
    url = _host_public(safe)
    is_reel = 0 < duration <= REEL_MAX_SECONDS
    creation_id = _create_container(ig_id, url, caption, is_reel)
    _wait_finished(creation_id)
    r = requests.post(f"{API}/{ig_id}/media_publish",
                      data={"creation_id": creation_id, "access_token": _token()},
                      timeout=60)
    r.raise_for_status()
    return r.json().get("id", creation_id)


class GraphClient:
    """Mimics the instagrapi client interface used by instagram_upload.py."""

    def dump_settings(self, *args, **kwargs):
        return None  # official API uses a long-lived token, no session to persist

    def clip_upload(self, path, caption, thumbnail=None):
        pk = publish(path, caption, duration=REEL_MAX_SECONDS)
        return type("M", (), {"pk": pk})()

    def video_upload(self, path, caption, thumbnail=None):
        pk = publish(path, caption, duration=999)
        return type("M", (), {"pk": pk})()
