"""Social media platform posters — one function per platform.

Each platform supports MULTIPLE accounts (stored in social_accounts.json).
Free platforms: YouTube (Data API), Instagram (Graph API), Facebook (Graph API).
Paid/approval platforms: X, LinkedIn (stored but flagged as needing access).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent


def load_accounts() -> dict:
    p = BASE / "social_accounts.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_accounts(data: dict) -> None:
    (BASE / "social_accounts.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------- YouTube (FREE, Data API v3, OAuth) ----------------
def youtube_post(account: dict, file: str, title: str, desc: str,
                 tags: list[str], privacy: str = "private",
                 publish_at: str | None = None) -> dict:
    """Upload a video to a YouTube channel via OAuth (token per channel)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_authorized_user_file(account["token_file"], SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError("YouTube token expired — re-auth this channel")
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": title[:100], "description": desc[:5000],
                        "tags": tags[:30], "categoryId": "22"},
            "status": {"privacyStatus": privacy,
                       "publishAt": publish_at,
                       "selfDeclaredMadeForKids": False}}
    media = MediaFileUpload(file, chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
    return {"ok": True, "id": resp["id"], "platform": "youtube"}


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


# ---------------- Instagram (FREE, Graph API) ----------------
def instagram_post(account: dict, file: str, caption: str,
                   media_type: str = "reels", duration: int = 0) -> dict:
    """Post a reel/video to an Instagram Business account (long-lived token)."""
    import sys
    sys.path.insert(0, str(BASE))
    import instagram_graph as ig
    # use the account's own token/id
    ig_id = account["ig_user_id"]
    token = account["graph_token"]
    url = ig._host_public(file)
    safe = ig._transcode(file)
    is_reel = media_type == "reels" or (0 < duration <= 90)
    r = requests.post(f"https://graph.facebook.com/v21.0/{ig_id}/media",
                      data={"caption": caption, "video_url": ig._host_public(safe),
                            "media_type": "REELS" if is_reel else "VIDEO",
                            "access_token": token}, timeout=60)
    r.raise_for_status()
    creation_id = r.json()["id"]
    # poll
    for _ in range(40):
        pr = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}",
                          params={"fields": "status_code", "access_token": token},
                          timeout=30)
        pr.raise_for_status()
        code = pr.json().get("status_code", "")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError("Instagram rejected container")
        time.sleep(10)
    pb = requests.post(f"https://graph.facebook.com/v21.0/{ig_id}/media_publish",
                       data={"creation_id": creation_id, "access_token": token},
                       timeout=60)
    pb.raise_for_status()
    return {"ok": True, "id": pb.json().get("id", creation_id),
            "platform": "instagram"}


# ---------------- Facebook (FREE, Graph API page token) ----------------
def facebook_post(account: dict, file: str, message: str) -> dict:
    """Post a video to a Facebook Page (page access token)."""
    ig_id = account["page_id"]
    token = account["page_token"]
    url = instagram_post.__globals__["ig"]._host_public(file)  # reuse hoster
    r = requests.post(f"https://graph.facebook.com/v21.0/{ig_id}/videos",
                      data={"description": message, "access_token": token},
                      files={"file": open(file, "rb")}, timeout=300)
    r.raise_for_status()
    return {"ok": True, "id": r.json().get("id"), "platform": "facebook"}


# ---------------- X (FREE via twikit account login; bearer = paid) ----------------
def x_post(account: dict, text: str, media_ids: list[str] | None = None) -> dict:
    """Post to X. Free path: twikit (username/password login, like a
    real app). Paid path: official API bearer token."""
    user, pw = account.get("username"), account.get("password")
    if user and pw:
        from twikit import Client
        cl = Client("en-US")
        cl.login(auth_info_1=user, auth_info_2=pw)
        tw = cl.post_tweet(text=text[:280])
        return {"ok": True, "id": tw.id, "platform": "x",
                "mode": "twikit (free)"}
    token = account["bearer_token"]
    r = requests.post("https://api.twitter.com/2/tweets",
                      json={"text": text[:280]},
                      headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return {"ok": True, "id": r.json()["data"]["id"], "platform": "x",
            "mode": "official API"}


# ---------------- LinkedIn (PAID/approval: Marketing API) ----------------
def linkedin_post(account: dict, text: str) -> dict:
    token = account["access_token"]
    urn = account["organization_urn"]
    r = requests.post("https://api.linkedin.com/v2/shares",
                      json={"author": urn,
                            "lifecycleState": "PUBLISHED",
                            "specificContent": {
                                "com.linkedin.ugc.ShareContent": {
                                    "shareCommentary": {"text": text},
                                    "shareMediaCategory": "NONE"}},
                            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}},
                      headers={"Authorization": f"Bearer {token}",
                               "X-Restli-Protocol-Version": "2.0.0"}, timeout=30)
    r.raise_for_status()
    return {"ok": True, "id": r.json().get("id"), "platform": "linkedin"}


# ---------------- Bluesky (FREE, official atproto API) ----------------
def bluesky_post(account: dict, text: str, image: str | None = None) -> dict:
    """Bluesky via the FREE official atproto API (app password)."""
    handle, pw = account["handle"], account["app_password"]
    r = requests.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": pw}, timeout=30)
    r.raise_for_status()
    access = r.json()["accessJwt"]
    did = r.json()["did"]
    rec: dict = {"text": text[:300], "createdAt": time.strftime(
        "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}
    if image:
        with open(image, "rb") as f:
            up = requests.post(
                "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                headers={"Authorization": f"Bearer {access}",
                           "Content-Type": "image/jpeg"}, data=f, timeout=60)
        up.raise_for_status()
        rec["embed"] = {"$type": "app.bsky.embed.images",
                          "images": [{"alt": "", "image": up.json()["blob"]}]}
    r = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        json={"repo": did, "collection": "app.bsky.feed.post",
              "record": rec},
        headers={"Authorization": f"Bearer {access}"}, timeout=30)
    r.raise_for_status()
    return {"ok": True, "id": r.json().get("uri"), "platform": "bluesky"}


# ---------------- Telegram (FREE, official bot API) ----------------
def telegram_post(account: dict, text: str,
                  video: str | None = None) -> dict:
    """Telegram via the FREE official bot API (bot token)."""
    token, chat_id = account["bot_token"], account["chat_id"]
    base = f"https://api.telegram.org/bot{token}"
    if video:
        with open(video, "rb") as f:
            r = requests.post(f"{base}/sendVideo",
                              data={"chat_id": chat_id,
                                      "caption": text[:1024]},
                              files={"video": f}, timeout=300)
    else:
        r = requests.post(f"{base}/sendMessage",
                          data={"chat_id": chat_id, "text": text[:4096]},
                          timeout=30)
    r.raise_for_status()
    return {"ok": True, "id": r.json()["result"]["message_id"],
            "platform": "telegram"}


# ---------------- Approval-gated: browser fallback is the way ----------
def tiktok_post(account: dict, file: str, title: str) -> dict:
    raise RuntimeError("TikTok API needs approval — use Post (Browser)")


def threads_post(account: dict, text: str) -> dict:
    raise RuntimeError("Threads API is Meta-limited — use Post (Browser)")


def pinterest_post(account: dict, image: str, title: str,
                   link: str = "") -> dict:
    raise RuntimeError("Pinterest API needs an app — use Post (Browser)")


POSTERS = {
    "youtube": youtube_post,
    "instagram": instagram_post,
    "facebook": facebook_post,
    "x": x_post,
    "linkedin": linkedin_post,
    "bluesky": bluesky_post,
    "telegram": telegram_post,
    "tiktok": tiktok_post,
    "threads": threads_post,
    "pinterest": pinterest_post,
}

# Which platforms support free posting right now
FREE_PLATFORMS = {"youtube", "instagram", "facebook", "bluesky",
                  "telegram"}

# Which platforms support free posting right now
FREE_PLATFORMS = {"youtube", "instagram", "facebook"}
