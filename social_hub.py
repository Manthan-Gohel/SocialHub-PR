"""SocialHub — multi-platform social media dashboard (stdlib only).

Platforms: Instagram, X, LinkedIn, YouTube, Facebook (extensible).
Each platform supports MULTIPLE accounts (different names/credentials).
Features: add/remove accounts, post (video/reel/short/story/text),
AI SEO optimization, and humanized multi-account comment automation.

Run:  .venv\\Scripts\\python.exe social_hub.py
Then open http://localhost:8090
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import social_platforms as sp   # noqa: E402
import ai_engine as ai          # noqa: E402

BASE = Path(__file__).resolve().parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
UPLOAD_DIR = BASE / "uploads"
ACCOUNTS_FILE = BASE / "social_accounts.json"
POSTS_FILE = BASE / "social_posts.json"
COMMENTS_FILE = BASE / "social_comments.json"

PLATFORMS = {
    "instagram": {
        "label": "Instagram",
        "fields": [("name", "Account name (label)"),
                   ("description", "Description (e.g. celebrity gossip)"),
                   ("link", "Profile link (opens in browser)"),
                   ("ig_user_id", "IG User ID (API)"),
                   ("graph_token", "Long-lived Graph token (API)"),
                   ("username", "Instagram username (browser)"),
                   ("password", "Instagram password (browser only)")],
        "types": ["reels", "video", "post", "story"],
        "free": True,
    },
    "youtube": {
        "label": "YouTube",
        "fields": [("name", "Account name"),
                   ("description", "Description (e.g. tech shorts)"),
                   ("link", "Channel link (opens in browser)"),
                   ("token_file", "OAuth token file (API)"),
                   ("username", "Google email (browser)"),
                   ("password", "Google password (browser only)")],
        "types": ["shorts", "video"],
        "free": True,
    },
    "facebook": {
        "label": "Facebook",
        "fields": [("name", "Account name"), ("page_id", "Page ID"),
                   ("page_token", "Page access token")],
        "types": ["video"],
        "free": True,
    },
    "x": {
        "label": "X (Twitter)",
        "fields": [("name", "Account name"),
                   ("username", "X username (free via twikit)"),
                   ("password", "X password (free via twikit)"),
                   ("bearer_token", "Bearer token (official API, paid)")],
        "types": ["text"],
        "free": True,   # twikit path is free
    },
    "linkedin": {
        "label": "LinkedIn",
        "fields": [("name", "Account name"), ("access_token", "Access token"),
                   ("organization_urn", "Organization URN")],
        "types": ["text"],
        "free": False,   # needs Marketing API approval
    },
    "bluesky": {
        "label": "Bluesky",
        "fields": [("name", "Account name"), ("handle", "Handle (you.bsky.social)"),
                   ("app_password", "App password")],
        "types": ["text"],
        "free": True,   # official atproto API, free
    },
    "telegram": {
        "label": "Telegram",
        "fields": [("name", "Account name"), ("bot_token", "Bot token"),
                   ("chat_id", "Channel / chat id")],
        "types": ["text"],
        "free": True,   # official bot API, free
    },
    "tiktok": {
        "label": "TikTok",
        "fields": [("name", "Account name"), ("link", "Profile link"),
                   ("username", "Username (browser)"),
                   ("password", "Password (browser only)")],
        "types": ["video"],
        "free": False,   # official Content Posting API needs approval
    },
    "threads": {
        "label": "Threads",
        "fields": [("name", "Account name"), ("link", "Profile link"),
                   ("username", "Username (browser)"),
                   ("password", "Password (browser only)")],
        "types": ["text"],
        "free": False,   # API is Meta-limited
    },
    "pinterest": {
        "label": "Pinterest",
        "fields": [("name", "Account name"), ("link", "Profile link"),
                   ("access_token", "API token (needs app)"),
                   ("username", "Username (browser)")],
        "types": ["pin"],
        "free": False,   # API needs an app
    },
}


def load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def accounts() -> dict:
    """Accounts from SQLite (hub.db) — migrated from JSON one-time."""
    import hubdb
    return hubdb.all_accounts()


def add_account(platform: str, acct: dict) -> str:
    data = accounts()
    data.setdefault(platform, [])
    uid = f"{platform[:2]}-{int(time.time())}"
    acct["_id"] = uid
    data[platform].append(acct)
    save(ACCOUNTS_FILE, data)
    return uid


def remove_account(platform: str, uid: str) -> None:
    data = accounts()
    data[platform] = [a for a in data.get(platform, [])
                      if a.get("_id") != uid]
    save(ACCOUNTS_FILE, data)


# ---------------- API logic ----------------
def do_seo(payload: dict) -> dict:
    title = payload.get("title", "")
    desc = payload.get("description", "")
    platform = payload.get("platform", "youtube")
    seed = payload.get("seed", "")
    return ai.generate_seo(title, desc, platform, seed=seed)


def do_gen_comments(payload: dict) -> dict:
    idea = payload.get("idea", "")
    count = int(payload.get("count", 5))
    comments = ai.generate_comments(idea, count)
    save(COMMENTS_FILE, {"idea": idea, "comments": comments})
    return {"comments": comments}


def do_post(payload: dict) -> dict:
    platform = payload["platform"]
    uid = payload["account_id"]
    acct = next((a for a in accounts().get(platform, [])
                 if a.get("_id") == uid), None)
    if not acct:
        return {"ok": False, "error": "account not found"}
    title = payload.get("title", "")
    desc = payload.get("description", "")
    media = payload.get("media_type", "video")
    file = payload.get("file", "")
    tags = payload.get("tags", ai.SEO_TAGS)
    poster = sp.POSTERS.get(platform)
    if not poster:
        return {"ok": False, "error": "unsupported platform"}
    try:
        if platform == "youtube":
            res = poster(acct, file, title, desc, tags,
                         privacy=payload.get("privacy", "private"),
                         publish_at=payload.get("publish_at"))
        elif platform == "instagram":
            res = poster(acct, file, desc,
                         media_type=media, duration=payload.get("duration", 0))
        elif platform == "facebook":
            res = poster(acct, file, desc)
        elif platform == "bluesky":
            res = poster(acct, desc, image=file or None)
        elif platform == "telegram":
            res = poster(acct, desc, video=file or None)
        elif platform == "pinterest":
            res = poster(acct, file, title, payload.get("link", ""))
        else:  # x / linkedin / tiktok / threads (text)
            res = poster(acct, desc)
        save(POSTS_FILE, load(POSTS_FILE, []) + [{
            "platform": platform, "account": acct.get("name"),
            "title": title, "at": time.strftime("%Y-%m-%d %H:%M")}])
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}


def do_post_browser(payload: dict) -> dict:
    """Spawn browser_poster.py for an account that has no API token.

    Opens a VISIBLE browser; the human completes login/2FA and the
    final share. Returns immediately (async subprocess)."""
    platform = payload.get("platform", "instagram")
    uid = payload.get("account_id")
    if not uid:
        return {"ok": False, "error": "missing account_id"}
    acct = next((a for a in accounts().get(platform, [])
                 if a.get("_id") == uid), None)
    if not acct:
        return {"ok": False, "error": "account not found"}
    if not acct.get("username") or not acct.get("password"):
        return {"ok": False, "error": "account needs username+password "
                                       "for browser posting"}
    file = payload.get("file", "")
    caption = payload.get("description", "")
    title = payload.get("title", "")
    media_type = payload.get("media_type", "reels")
    btype = ("video" if platform == "facebook"
               else "reel" if media_type in ("reels", "shorts")
               else "story" if media_type == "story" else "video")
    cmd = [sys.executable, str(BASE / "browser_poster.py"),
           "--platform", platform,
           "--username", acct["username"],
           "--password", acct["password"],
           "--video", file, "--caption", caption,
           "--title", title, "--type", btype]
    subprocess.Popen(cmd, cwd=str(BASE))
    return {"ok": True, "mode": "browser",
            "note": "Browser opened — complete login/2FA & share "
                    "in the visible window."}


def do_edit_account(payload: dict) -> dict:
    """Rename an account and set its description / link
    (local labels only — does NOT touch the real IG name)."""
    platform = payload.get("platform", "")
    uid = payload.get("uid")
    data = accounts()
    for a in data.get(platform, []):
        if a.get("_id") == uid:
            for k in ("name", "description", "link"):
                if k in payload:
                    a[k] = payload[k]
            save(ACCOUNTS_FILE, data)
            return {"ok": True, "account": a}
    return {"ok": False, "error": "account not found"}


def do_open_account(payload: dict) -> dict:
    """Open an account's profile link in a visible browser."""
    platform = payload.get("platform", "instagram")
    uid = payload.get("uid")
    acct = next((a for a in accounts().get(platform, [])
                 if a.get("_id") == uid), None)
    if not acct:
        return {"ok": False, "error": "account not found"}
    link = acct.get("link") or acct.get("username")
    if not link:
        return {"ok": False, "error": "no link/username saved"}
    if not link.startswith("http"):
        link = "https://www.instagram.com/" + link.lstrip("@") + "/"
    subprocess.Popen(["start", "", link], shell=True)
    return {"ok": True, "url": link}


def do_comment_browser(payload: dict) -> dict:
    """Spawn browser_commenter.py to comment on a URL from
    ONE account (visible browser, human-supervised)."""
    uid = payload.get("account_id")
    acct = next((a for a in accounts().get("instagram", [])
                 if a.get("_id") == uid), None)
    if not acct:
        return {"ok": False, "error": "account not found"}
    if not acct.get("username") or not acct.get("password"):
        return {"ok": False, "error": "account needs "
                   "username+password for browser commenting"}
    url = payload.get("url", "")
    text = payload.get("comment", "")
    if not url or not text:
        return {"ok": False, "error": "need url + comment"}
    cmd = [sys.executable, str(BASE / "browser_commenter.py"),
           "--username", acct["username"],
           "--password", acct["password"],
           "--url", url, "--comment", text]
    subprocess.Popen(cmd, cwd=str(BASE))
    return {"ok": True, "mode": "browser-comment",
            "note": "Browser opened — login/2FA then it "
                    "comments on the post."}


def do_post_multi(payload: dict) -> dict:
    """Post to MULTIPLE accounts — each gets a UNIQUE SEO title and
    description (different power word + CTA per account, always
    video-related). Enqueued to the job runner (never blocks the
    request); the Reviewer gates each account's output first."""
    platform = payload.get("platform", "instagram")
    uids = payload.get("account_ids", [])
    file = payload.get("file", "")
    raw_title = payload.get("title", "")
    raw_desc = payload.get("description", "")
    media_type = payload.get("media_type", "reels")
    dry = bool(payload.get("dry_run"))
    if not (file and uids):
        return {"ok": False, "error": "need file + account_ids"}
    import ai_engine as _ai
    import trust
    accts = hubdb_accounts().get(platform, [])
    jobs = []
    plan = []
    blocked = []
    # >3 accounts: LLM SEO per account is slow (~1 min each) —
    # enqueue raw data, SEO generated inside the background job
    if len(uids) > 3 and not dry:
        import job_runner
        import hubdb
        approved = []
        for uid in uids:
            a = next((x for x in accts if x.get("_id") == uid), None)
            if a and a.get("username"):
                approved.append({"username": a["username"],
                                   "password": a["password"]})
        if not approved:
            return {"ok": False, "error": "no accounts with "
                                           "username+password saved"}
        job_id = job_runner.enqueue("multi-post-seo", {
            "platform": platform, "file": file,
            "raw_title": raw_title, "raw_desc": raw_desc,
            "media_type": media_type, "jobs": approved})
        hubdb.log_event("multi_post_enqueued",
                          f"job#{job_id} (bg-SEO) accounts={len(approved)}")
        return {"ok": True, "dry_run": False, "count": len(approved),
                "note": f"Job #{job_id} queued — the worker generates "
                        f"a unique SEO title/description per account "
                        f"(LLM, ~1 min each) then posts one at a time. "
                        f"Poll /api/jobs for status."}
    for uid in uids:
        a = next((x for x in accts if x.get("_id") == uid), None)
        if not a or not a.get("username"):
            continue
        # unique SEO per account: seed with the account id
        seo = _ai.generate_seo(raw_title or "video", raw_desc,
                                 platform, seed=uid)
        # Reviewer gates each account's output before the queue
        review = trust.reviewer_check({
            "kind": "post", "title": seo["title"],
            "description": seo["description"], "file": file,
            "account": a})
        if review["verdict"] != "approved":
            blocked.append({"account": a.get("name"),
                              "issues": review["issues"]})
            continue
        jobs.append({
            "username": a["username"], "password": a["password"],
            "file": file,
            "title": seo["title"], "caption": seo["description"],
            "media_type": ("reel" if media_type in ("reels", "shorts")
                             else "video")})
        plan.append({"account": a.get("name") or a["username"],
                     "title": seo["title"],
                     "tags": seo["tags"][:5]})
    if not jobs:
        return {"ok": False, "error": "no approved accounts "
                                       "(reviewer blocked all)",
                "blocked": blocked}
    if not dry:
        import job_runner
        if len(jobs) > 3:
            # LLM SEO per account is slow — enqueue the whole thing
            # (SEO generated inside the job), return immediately
            job_id = job_runner.enqueue("multi-post-seo", {
                "platform": platform, "file": file,
                "raw_title": raw_title, "raw_desc": raw_desc,
                "media_type": media_type, "jobs": jobs})
            hubdb.log_event("multi_post_enqueued",
                              f"job#{job_id} (bg-SEO) accounts={len(jobs)}")
            note = (f"Job #{job_id} queued — the worker generates a "
                    f"unique SEO title/description per account "
                    f"(LLM, ~1 min each) then posts one at a time. "
                    f"Poll /api/jobs for status.")
        else:
            job_id = job_runner.enqueue("multi-post", {
                "platform": platform, "jobs": jobs})
            hubdb.log_event("multi_post_enqueued",
                              f"job#{job_id} accounts={len(jobs)}")
            note = (f"Job #{job_id} queued — worker runs it one "
                    f"account at a time. Poll /api/jobs for status.")
    else:
        note = "DRY RUN — nothing posted. Plan below is what WOULD run."
    return {"ok": True, "dry_run": dry, "count": len(jobs),
            "plan": plan, "blocked": blocked, "note": note}


def do_genre_trends(payload: dict) -> dict:
    """SCrawler-style: for a genre, what's trending NOW (live news
    keywords) + the genre's curated hashtags for SEO."""
    genre = payload.get("genre", "").strip()
    if not genre:
        return {"ok": False, "error": "need genre (e.g. gaming, comedy)"}
    import pr_team
    import ai_engine as _ai
    news = pr_team._news_mentions(genre, limit=10)
    headlines = [m["title"] for m in news[:8]]
    # common keywords across headlines (trending now)
    import re as _re
    from collections import Counter
    words = Counter()
    for h in headlines:
        for w in _re.findall(r"[a-zA-Z]{4,}", h.lower()):
            if w not in ("with", "this", "that", "have", "from", "what",
                         "says", "after", "over", "just", "their", "they"):
                words[w] += 1
    trending_now = [w for w, c in words.most_common(10) if c >= 2]
    cats = _ai.detect_categories(genre)
    tags = _ai.build_tags(genre, "instagram")
    return {"ok": True, "genre": genre,
            "detected_categories": cats,
            "genre_tags": tags,
            "trending_now": trending_now,
            "news_headlines": headlines}


def do_task(payload: dict) -> dict:
    """Chat task box: parse a natural-language task and
    queue/execute the actions across accounts."""
    import tasks as tk
    text = payload.get("task", "")
    ig_names = [a.get("name", "") for a in
                accounts().get("instagram", [])]
    actions = tk.parse_task(text, ig_names)
    results = []
    for act in actions:
        kind = act.get("action")
        if kind == "campaign":
            import company
            out = company.ceo_run(act.get("topic", ""), accounts())
            results.append({"action": "campaign",
                              "topic": out.get("goal"),
                              "decision": out.get("decision"),
                              "action_items": out.get("action_items"),
                              "workers_reports": [
                                  {"worker": w.get("worker"),
                                   "summary": w.get("summary")}
                                  for w in out.get("workers_reports", [])]})
        elif kind == "grow":
            import company
            target = act.get("target", "our accounts")
            out = company.ceo_run(f"grow {target}", accounts())
            results.append({"action": "grow", "target": target,
                              "decision": out.get("decision"),
                              "action_items": out.get("action_items"),
                              "workers_reports": [
                                  {"worker": w.get("worker"),
                                   "summary": w.get("summary")}
                                  for w in out.get("workers_reports", [])]})
        elif kind == "open":
            # find the account uid by name
            uid = _uid_by_name("instagram", act.get("account"))
            if uid:
                results.append(do_open_account(
                    {"platform": "instagram", "uid": uid}))
            else:
                results.append({"ok": False,
                                "error": f"account "
                                f"'{act.get('account')}' not found"})
        elif kind == "comment":
            for name in act.get("accounts", []):
                uid = _uid_by_name("instagram", name)
                if uid:
                    results.append(do_comment_browser({
                        "account_id": uid,
                        "url": act.get("url", ""),
                        "comment": act.get("text", "")}))
                else:
                    results.append({"ok": False,
                                    "error": f"account "
                                    f"'{name}' not found"})
        elif kind == "post":
            uid = _uid_by_name("instagram", act.get("account"))
            if uid:
                results.append({"ok": True, "queued": True,
                                "account": act.get("account"),
                                "title": act.get("title"),
                                "note": "Use the Post composer "
                                "with this title to publish."})
            else:
                results.append({"ok": False, "error":
                                f"account '{act.get('account')}' "
                                f"not found"})
    return {"ok": True, "task": text, "actions": actions,
            "results": results}


def _uid_by_name(platform: str, name: str) -> str | None:
    for a in accounts().get(platform, []):
        if a.get("name", "").lower() == (name or "").lower():
            return a.get("_id")
    return None


def _parse_multipart(content_type: str, body: bytes) -> dict:
    """Minimal multipart/form-data parser (stdlib email module)."""
    import email
    import email.policy
    raw = (b"Content-Type: " + content_type.encode()
             + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    msg = email.message_from_bytes(raw, policy=email.policy.HTTP)
    out: dict = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        data = part.get_payload(decode=True)
        if part.get_filename():
            out[name] = {"filename": part.get_filename(), "data": data}
        else:
            out[name] = (data or b"").decode("utf-8", "replace")
    return out


def analyze_video(path: str) -> dict:
    """ffprobe the video: duration, resolution, codec → suggest type."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=120)
    try:
        meta = json.loads(r.stdout or "{}")
    except Exception:
        meta = {}
    vs = next((s for s in meta.get("streams", [])
               if s.get("codec_type") == "video"), {})
    fmt = meta.get("format", {})
    dur = float(fmt.get("duration") or 0)
    w = int(vs.get("width") or 0)
    h = int(vs.get("height") or 0)
    codec = vs.get("codec_name", "")
    vertical = h > w
    return {"ok": True, "file": path, "duration": round(dur, 1),
            "width": w, "height": h, "codec": codec,
            "vertical": vertical,
            "suggested_type": ("reels" if (0 < dur <= 90 and vertical)
                                 else "video"),
            "suggested_yt": ("shorts" if (0 < dur <= 180 and vertical)
                               else "video")}


def do_upload(payload: dict) -> dict:
    """Save an uploaded video and analyze it."""
    f = payload.get("file")
    if not isinstance(f, dict) or not f.get("data"):
        return {"ok": False, "error": "no file received"}
    safe = f"{int(time.time())}_{Path(f['filename'] or 'video.mp4').name}"
    UPLOAD_DIR.mkdir(exist_ok=True)
    dest = UPLOAD_DIR / safe
    dest.write_bytes(f["data"])
    return analyze_video(str(dest))


# ---------------- PR Team endpoints ----------------
def pr_analytics() -> dict:
    import pr_team
    return pr_team.analytics_snapshot(accounts())


def _env(key: str) -> str | None:
    p = BASE / ".env"
    if not p.exists():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def do_refresh_token(payload: dict) -> dict:
    """Exchange the long-lived IG token for a fresh 60-day one
    (Facebook fb_exchange_token). Updates every account that uses it."""
    old = payload.get("graph_token")
    if not old:
        for a in accounts().get("instagram", []):
            if a.get("graph_token"):
                old = a["graph_token"]
                break
    app_id = _env("INSTAGRAM_APP_ID")
    app_secret = _env("INSTAGRAM_APP_SECRET")
    if not (old and app_id and app_secret):
        return {"ok": False, "error": "need graph_token (in an account) "
                "+ INSTAGRAM_APP_ID/SECRET in .env"}
    import requests as rq
    r = rq.get(
        "https://graph.facebook.com/v21.0/oauth/access_token",
        params={"grant_type": "fb_exchange_token",
                "client_id": app_id, "client_secret": app_secret,
                "fb_exchange_token": old}, timeout=30)
    j = r.json()
    if "access_token" not in j:
        return {"ok": False, "error": j.get("error", {}).get(
            "message", "refresh failed")[:300]}
    new_tok = j["access_token"]
    # verify + update accounts that used the old token
    import requests as rq2
    v = rq2.get("https://graph.facebook.com/v21.0/me",
                params={"access_token": new_tok}, timeout=30)
    ok = v.status_code == 200
    updated = 0
    data = accounts()
    for plats in data.values():
        for a in plats:
            if a.get("graph_token") == old:
                a["graph_token"] = new_tok
                updated += 1
    save(ACCOUNTS_FILE, data)
    # also update .env (add or replace INSTAGRAM_GRAPH_TOKEN)
    env = (BASE / ".env")
    txt = env.read_text(encoding="utf-8")
    if f"INSTAGRAM_GRAPH_TOKEN={old}" in txt:
        txt = txt.replace(f"INSTAGRAM_GRAPH_TOKEN={old}",
                            f"INSTAGRAM_GRAPH_TOKEN={new_tok}")
    else:
        txt += f"\nINSTAGRAM_GRAPH_TOKEN={new_tok}\n"
    env.write_text(txt, encoding="utf-8")
    return {"ok": ok, "updated_accounts": updated,
            "new_token_prefix": new_tok[:20] + "...",
            "note": "Token refreshed (~60 days) and saved to accounts "
                    "+ .env."}


def pr_monitor(payload: dict) -> dict:
    import pr_team
    return pr_team.monitor_mentions(payload.get("topic", ""))


def pr_crisis(payload: dict) -> dict:
    import pr_team
    return pr_team.crisis_plan(payload.get("topic", ""))


def pr_strategy(payload: dict) -> dict:
    import pr_team
    return pr_team.strategy_doc(payload.get("topic", ""), accounts())


def pr_full(payload: dict) -> dict:
    import pr_team
    return pr_team.full_package(payload.get("topic", ""), accounts())


def company_run(payload: dict) -> dict:
    import company
    return company.ceo_run(payload.get("goal", ""), accounts())


def _cancel_job(payload: dict) -> dict:
    import job_runner, hubdb
    hubdb.cancel_job(int(payload.get("job_id", 0)))
    return {"ok": True, "note": f"Job #{payload.get('job_id')} cancelled"}


def do_migrate(payload: dict) -> dict:
    import hubdb
    n = hubdb.migrate_accounts_from_json()
    return {"ok": True, "migrated": n}


def _fleet() -> dict:
    import fleet
    return fleet.fleet()


def _calendar() -> dict:
    import fleet
    return fleet.calendar()


def _reschedule(payload: dict) -> dict:
    import fleet
    return fleet.reschedule(payload)


def _canary() -> dict:
    import fleet
    return fleet.canary()


def _competitors() -> dict:
    import hubdb
    with hubdb.conn() as c:
        rows = c.execute("SELECT * FROM competitors ORDER BY id DESC "
                           "LIMIT 50").fetchall()
    return {"ok": True, "competitors": [dict(r) for r in rows]}


def _competitor_cron(payload: dict) -> dict:
    import fleet
    handles = [h.strip() for h in (payload.get("handles") or "")
               if isinstance(h, str)] or \
        [h.strip() for h in (payload.get("handles_str") or "").split(",")
         if h.strip()]
    return fleet.competitor_cron(handles, payload.get("platform",
                                                        "instagram"))


def _inbox(payload: dict) -> dict:
    import hubdb
    return {"ok": True, "inbox": hubdb.list_inbox(payload.get("status",
                                                                ""))}


def _inbox_fetch(payload: dict) -> dict:
    import inbox
    acct = next((a for a in accounts().get("instagram", [])
                 if a.get("_id") == payload.get("account_id")), None)
    if not acct:
        return {"ok": False, "error": "account not found"}
    return inbox.fetch_browser(acct, payload.get("platform", "instagram"))


def _inbox_reply(payload: dict) -> dict:
    """Generate a voice-guided reply (Reviewer-gated) and open the
    browser to post it. Add 'browser': false to only generate."""
    import inbox, hubdb
    acct = next((a for a in hubdb.all_accounts().get("instagram", [])
                 if a.get("_id") == payload.get("account_id")), None)
    items = hubdb.list_inbox()
    item = next((i for i in items
                 if i["id"] == int(payload.get("item_id", 0))), None)
    if not acct or not item:
        return {"ok": False, "error": "account or item not found"}
    out = inbox.generate_reply(item, acct)
    if not payload.get("browser", True) or \
            out.get("reviewer") != "approved":
        hubdb.mark_inbox(item["id"], "replied" if
                           out.get("reviewer") == "approved" else "ignored",
                           out["reply"]) if payload.get("browser") is False \
            else None
        return {**out, "note": "reply generated — copy it, or fix "
                                 "reviewer issues"}
    inbox.reply_browser(acct, payload.get("url", item.get("url", "")),
                          out["reply"])
    hubdb.mark_inbox(item["id"], "replied", out["reply"])
    return {**out, "note": "reply posted via browser"}


def _repurpose(payload: dict) -> dict:
    import growth
    return growth.repurpose(payload.get("video", ""),
                              dry_run=bool(payload.get("dry_run")))


def _ideas(payload: dict) -> dict:
    import growth
    return growth.ideas(payload.get("topic", ""))


def _weekly(payload: dict) -> dict:
    import growth
    return growth.weekly_report(payload.get("send_to", ""))


def _feedback(payload: dict) -> dict:
    import growth
    return growth.feedback_loop(int(payload.get("hours", 24)))


def _browser_jobs(platform: str, uids: list[str], url: str,
                  comments: list[str], watch: bool) -> dict:
    """Build the jobs file for browser_commenter.run_multi."""
    jobs = []
    accts = accounts().get(platform, [])
    for i, uid in enumerate(uids):
        a = next((x for x in accts if x.get("_id") == uid), None)
        if not a:
            continue
        if not a.get("username") or not a.get("password"):
            continue
        jobs.append({"username": a["username"],
                       "password": a["password"],
                       "comment": comments[i] if i < len(comments) else ""})
    return {"platform": platform, "url": url, "watch": watch,
            "jobs": jobs}


def _spawn_commenter(jobs: dict) -> str:
    path = BASE / "jobs_pending.json"
    path.write_text(json.dumps(jobs, ensure_ascii=False),
                      encoding="utf-8")
    subprocess.Popen([sys.executable, str(BASE / "browser_commenter.py"),
                        "--jobs-file", str(path)], cwd=str(BASE))
    return str(path)


def do_watch_multi(payload: dict) -> dict:
    """Open a video URL in a separate browser session per account so
    a human can watch it from each account (research, not botting)."""
    platform = payload.get("platform", "instagram")
    url = payload.get("url", "")
    uids = payload.get("account_ids", [])
    if not url or not uids:
        return {"ok": False, "error": "need url + account_ids"}
    jobs = _browser_jobs(platform, uids, url, [], watch=True)
    if not jobs["jobs"]:
        return {"ok": False, "error": "no accounts with "
                                       "username+password saved"}
    _spawn_commenter(jobs)
    return {"ok": True, "platform": platform,
            "accounts": [j["username"] for j in jobs["jobs"]],
            "mode": "watch",
            "note": "One browser at a time — it browses the feed "
                    "naturally first, then opens the linked video. "
                    "Press Enter in each window when done."}


def do_comment_multi(payload: dict) -> dict:
    """Generate a UNIQUE humanized comment per account and comment
    from each account in its own browser session (human-supervised)."""
    platform = payload.get("platform", "instagram")
    url = payload.get("url", "")
    uids = payload.get("account_ids", [])
    idea = payload.get("idea", "")
    if not url or not uids or not idea:
        return {"ok": False, "error": "need url + idea + account_ids"}
    import ai_engine as _ai
    accts = accounts().get(platform, [])
    names = []
    for uid in uids:
        a = next((x for x in accts if x.get("_id") == uid), None)
        if a:
            names.append(a.get("username") or a.get("name") or uid)
    comments = _ai.generate_comments(idea, count=max(len(uids), 1),
                                       seed=url)
    jobs = _browser_jobs(platform, uids, url, comments, watch=False)
    if not jobs["jobs"]:
        return {"ok": False, "error": "no accounts with "
                                       "username+password saved"}
    _spawn_commenter(jobs)
    return {"ok": True, "platform": platform,
            "plan": [{"account": n, "comment": c}
                     for n, c in zip(names, comments)],
            "mode": "comment",
            "note": "Each account posts a DIFFERENT comment, after "
                    "browsing the feed naturally. One browser at a "
                    "time — you supervise each."}


def do_learn_reel(payload: dict) -> dict:
    """Analyze a reel: hashtags, views, likes, insights."""
    url = payload.get("url", "")
    if not url:
        return {"ok": False, "error": "need url"}
    proc = subprocess.run(
        [sys.executable, str(BASE / "reel_learner.py"), "--url", url,
         *( ["--username", payload["username"], "--password",
             payload["password"]] if payload.get("username") else [] ),
         *( ["--save-tags"] if payload.get("save_tags") else [] )],
        capture_output=True, text=True, cwd=str(BASE), timeout=180)
    out = proc.stdout.strip()
    if not out:
        err = (proc.stderr or "no output").strip()[-400:]
        return {"ok": False, "error": err}
    try:
        return json.loads(out)
    except Exception:
        return {"ok": False, "error": "parse failed", "raw": out[-400:]}


def hubdb_accounts() -> dict:
    """SQLite-backed accounts (with voice/pillars/banned_topics)."""
    import hubdb
    return hubdb.all_accounts()


def do_post_comments(payload: dict) -> dict:
    """Post (or print) humanized comments across selected accounts."""
    comments = payload.get("comments", [])
    targets = payload.get("accounts", [])  # list of "platform:uid"
    results = []
    # Most social platforms have NO public comment API for arbitrary URLs
    # (Instagram/YouTube comment-on-anyone's-post requires special access).
    # So we produce the humanized comments ready to paste, and auto-post
    # only where the account's own API supports it (YouTube own videos).
    for c in comments:
        results.append({"comment": c, "targets": targets})
    return {"ok": True, "posted": results,
            "note": "Comments generated (humanized). Paste them on the "
                    "target post, or use the platform's own-comment API."}


# ---------------- HTML ----------------
HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SocialHub — Multi-Platform Poster</title>
<style>
:root{--bg:#0a0d12;--card:#11151d;--card2:#161b26;--border:#1e2633;--border2:#2a3547;
--txt:#e6e9ef;--dim:#8b93a3;--acc:#3b82f6;--acc2:#60a5fa;--ok:#34d399;--warn:#fbbf24;--bad:#f87171}
*{box-sizing:border-box;font-family:'Segoe UI',system-ui,-apple-system,sans-serif}
body{margin:0;background:radial-gradient(1200px 800px at 80% -10%,#101827 0%,var(--bg) 55%);color:var(--txt)}
.topbar{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:14px;
padding:10px 22px;background:rgba(13,17,23,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
.topbar .logo{font-weight:700;font-size:16px;letter-spacing:.3px}
.topbar .logo b{color:var(--acc2)}
.chip{font-size:11px;padding:3px 10px;border-radius:20px;border:1px solid var(--border2);color:var(--dim)}
.chip.ok{color:var(--ok);border-color:rgba(52,211,153,.35)}
.chip.warn{color:var(--warn);border-color:rgba(251,191,36,.35)}
.nav{width:228px;background:transparent;min-height:calc(100vh - 53px);padding:14px 12px;position:fixed;top:53px}
.nav a{display:flex;align-items:center;gap:9px;color:var(--dim);text-decoration:none;
padding:9px 12px;border-radius:9px;margin-bottom:2px;cursor:pointer;font-size:13.5px;
border:1px solid transparent;transition:all .15s}
.nav a:hover{background:var(--card2);color:var(--txt)}
.nav a.on{background:linear-gradient(90deg,rgba(59,130,246,.16),rgba(59,130,246,.04));
color:#fff;border-color:rgba(59,130,246,.3)}
.main{margin-left:244px;padding:22px 26px;max-width:1120px}
.card{background:linear-gradient(180deg,var(--card) 0%,#0e1218 100%);border:1px solid var(--border);
border-radius:14px;padding:20px;margin-bottom:18px;box-shadow:0 4px 24px rgba(0,0,0,.35)}
.card h3{margin:0 0 4px;color:#fff;font-size:15.5px;display:flex;align-items:center;gap:8px}
.card .sub{font-size:12px;color:var(--dim);margin-bottom:10px}
label{display:block;font-size:11.5px;color:var(--dim);margin:9px 0 4px;text-transform:uppercase;letter-spacing:.5px}
input,select,textarea{width:100%;background:#0b0f16;border:1px solid var(--border2);color:var(--txt);
padding:9px 11px;border-radius:9px;font-size:13px;outline:none;transition:border .15s}
input:focus,select:focus,textarea:focus{border-color:var(--acc)}
textarea{min-height:80px;resize:vertical}
button{background:linear-gradient(180deg,var(--acc) 0%,#2563eb 100%);color:#fff;border:0;
padding:9px 15px;border-radius:9px;cursor:pointer;font-size:13px;margin-top:10px;font-weight:600;
transition:all .15s;box-shadow:0 2px 10px rgba(59,130,246,.25)}
button.sec{background:var(--card2);border:1px solid var(--border2);box-shadow:none;color:var(--txt)}
button:hover{filter:brightness(1.12);transform:translateY(-1px)}
button:active{transform:translateY(0)}
.row{display:flex;gap:10px;flex-wrap:wrap}
.acct{border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin:7px 0;
display:flex;justify-content:space-between;align-items:center;background:#0d1118;transition:border .15s}
.acct:hover{border-color:var(--border2)}
.badge{font-size:10.5px;padding:2px 8px;border-radius:20px;background:var(--card2);
color:var(--dim);border:1px solid var(--border)}
.free{color:var(--ok)}.paid{color:var(--warn)}
pre{white-space:pre-wrap;background:#0b0f16;border:1px solid var(--border);padding:12px;
border-radius:10px;font-size:12px;line-height:1.55;color:#c7ceda;max-height:480px;overflow:auto}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.qbtns{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 4px}
.qbtns button{margin-top:0;padding:7px 12px;font-size:12px}
.laptops{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.laptop{background:linear-gradient(180deg,#0d1118,#0b0f16);border:1px solid var(--border2);
border-radius:12px;overflow:hidden;box-shadow:0 4px 18px rgba(0,0,0,.4)}
.laptop .screen{padding:12px 14px;border-bottom:1px solid var(--border)}
.laptop .name{font-weight:700;font-size:13px;display:flex;justify-content:space-between;align-items:center}
.laptop .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.laptop .dot.active{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.laptop .dot.idle{background:#3a4356}
.laptop .meta{font-size:11px;color:var(--dim);margin-top:6px;line-height:1.5}
.laptop .base{height:6px;background:linear-gradient(180deg,#2a3547,#1a2230);border-radius:0 0 4px 4px}
@media(max-width:860px){.two{grid-template-columns:1fr}.nav{position:static;width:100%;min-height:0}
.main{margin-left:0}}
</style></head><body>
<div class="topbar">
  <div class="logo">Social<b>Hub</b> PR</div>
  <span class="chip" id="stLlm">LLM: …</span>
  <span class="chip" id="stAccts">Accounts: …</span>
  <span class="chip ok" id="stServer">● Live · :8090</span>
</div>
<div class="nav">
  <h2>SocialHub</h2>
  <a data-p="instagram" class="on">Instagram</a>
  <a data-p="x">X (Twitter)</a>
  <a data-p="linkedin">LinkedIn</a>
  <a data-p="youtube">YouTube</a>
  <a data-p="facebook">Facebook</a>
  <a data-p="seo">AI SEO</a>
  <a data-p="comments">Comments AI</a>
  <a data-p="learn">📚 Learn</a>
  <a data-p="tasks">🤖 Tasks (chat)</a>
  <a data-p="pr">🎯 PR Team</a>
  <a data-p="company">🏢 Company</a>
  <a data-p="fleet">💻 Fleet (agent laptops)</a>
  <a data-p="calendar">📅 Calendar</a>
  <a data-p="competitors">🥊 Competitors</a>
  <a data-p="inbox">📥 Inbox + Reply AI</a>
  <a data-p="growth">♻️ Growth loop</a>
</div>
<div class="main">
  <div class="card" id="acctCard">
    <h3 id="platTitle">Instagram</h3>
    <div id="acctList"></div>
    <div id="addForm"></div>
  </div>
  <div class="card">
    <h3>Create Post</h3>
    <div class="row">
      <div style="flex:1"><label>Platform</label><select id="pPlatform" onchange="refreshAccounts()"></select></div>
      <div style="flex:1"><label>Account</label><select id="pAccount"></select></div>
      <div style="flex:1"><label>Type</label><select id="pType"></select></div>
    </div>
    <label>Raw title / idea</label><input id="pTitle">
    <label>Raw description</label><textarea id="pDesc"></textarea>
    <div class="row">
      <div style="flex:1"><label>Video file (pick it — auto-analyzed, no path typing)</label><input type="file" id="pFilePick" accept="video/*" onchange="uploadFile()"><input type="hidden" id="pFile"><div class="badge" id="pFileInfo"></div></div>
      <div style="flex:1"><label>Publish at (optional, YYYY-MM-DD HH:MM)</label><input id="pWhen"></div>
    </div>
    <div class="row">
      <button onclick="seo()">✨ AI SEO</button>
      <button class="sec" onclick="post()">📤 Post (API)</button>
      <button class="sec" onclick="postBrowser()">🌐 Post (Browser)</button>
    </div>
    <pre id="postOut"></pre>
    <h3 style="margin-top:14px">Multi-Post — checkbox which accounts post, different title/desc each</h3>
    <div class="two">
      <div><label>Accounts (tick the checkbox of who posts)</label><div id="mpAccounts"></div></div>
      <div><label>Raw title/idea (video-related — each account gets its own unique version)</label><input id="mpTitle"></div>
    </div>
    <button class="sec" onclick="multiPost()">📤 Multi-Post (unique SEO each)</button>
    <pre id="mpOut"></pre>
  </div>
  <div class="card" id="seoCard" style="display:none">
    <h3>AI SEO Optimizer</h3>
    <label>Platform</label><select id="seoPlat"><option>youtube</option><option>instagram</option><option>facebook</option></select>
    <label>Raw title</label><input id="seoTitle">
    <label>Raw description</label><textarea id="seoDesc"></textarea>
    <button onclick="runSeo()">Optimize</button>
    <pre id="seoOut"></pre>
    <h3 style="margin-top:14px">Genre trends (SCrawler-style)</h3>
    <label>Genre / topic (e.g. gaming, comedy, food)</label><input id="gGenre" placeholder="gaming">
    <button onclick="genreTrends()">🔥 What's trending in this genre</button>
    <pre id="gOut"></pre>
  </div>
  <div class="card" id="cmtCard" style="display:none">
    <h3>Humanized Comment Automation</h3>
    <div class="two">
      <div><label>Post URL / link</label><input id="cUrl"><label>Your raw idea / what to say</label><textarea id="cIdea"></textarea><label>Number of comments</label><input id="cCount" type="number" value="5"></div>
      <div><label>Target accounts (platform:uid, comma sep)</label><textarea id="cTargets" placeholder="instagram:ig-123, youtube:yt-456"></textarea></div>
    </div>
    <button onclick="genComments()">🧠 Generate humanized comments</button>
    <button class="sec" onclick="postComments()">📤 Post comments</button>
    <pre id="cmtOut"></pre>
    <h3 style="margin-top:16px">Multi-account actions (browser, human-supervised)</h3>
    <div class="two">
      <div><label>Platform</label><select id="mPlat" onchange="fillCommentAccts()"><option value="instagram">Instagram</option><option value="youtube">YouTube</option><option value="facebook">Facebook</option></select><label>Post/reel/video URL</label><input id="bUrl" placeholder="https://www.instagram.com/reel/ABC/ or https://youtu.be/XYZ"><label>Comment idea (each account gets a DIFFERENT comment)</label><input id="bText" placeholder="great editing skills"></div>
      <div><label>Accounts (Ctrl+click for multiple)</label><select id="bAcct" multiple size="6"></select></div>
    </div>
    <button class="sec" onclick="multiAction('watch')">👀 Watch from accounts</button>
    <button class="sec" onclick="multiAction('comment')">💬 Comment (unique per account)</button>
    <pre id="bOut"></pre>
  </div>
  <div class="card" id="learnCard" style="display:none">
    <h3>📚 Learn from reels — how did it get its views?</h3>
    <label>Reel URL</label><input id="lUrl" placeholder="https://www.instagram.com/reel/ABC/">
    <label>Instagram account (optional, if login wall)</label><select id="lAcct"></select>
    <label><input type="checkbox" id="lSave" checked style="width:auto"> Save its hashtags into trending tags (future SEO learns)</label>
    <button onclick="learnReel()">🔍 Analyze reel</button>
    <pre id="learnOut"></pre>
  </div>
  <div class="card" id="taskCard" style="display:none">
    <h3>🤖 Chat Tasks</h3>
    <div class="sub">Touch a quick button or type any task — the agents do all the work.</div>
    <div class="qbtns">
      <button onclick="quickTask('⚡ FULL campaign for ')">⚡ Full campaign</button>
      <button onclick="quickTask('scout op for ')">🔍 Scout opportunities</button>
      <button onclick="quickTask('grow ')">📈 Grow account</button>
      <button class="sec" onclick="quickTask('crisis plan for ')">🚨 Crisis plan</button>
      <button class="sec" onclick="quickTask('analytics')">📊 Analytics</button>
      <button class="sec" onclick="quickTask('open ')">🌐 Open account</button>
    </div>
    <label>Chat — type anything (e.g. bigboss win scout op)</label>
    <textarea id="tInput" placeholder="Type your task here, then press Run or Enter..."></textarea>
    <button onclick="runTask()">▶ Run</button>
    <pre id="taskOut"></pre>
  </div>
  <div class="card" id="prCard" style="display:none">
    <h3>🎯 PR Team — fully agentic</h3>
    <label>Topic / subject (e.g. celebrity gossip, my brand, a crisis)</label>
    <input id="prTopic" placeholder="celebrity X gossip">
    <div class="row">
      <button onclick="prCall('analytics')">📊 Analytics (real)</button>
      <button onclick="prCall('monitor')">🔍 Monitor mentions</button>
      <button onclick="prCall('communities')">🤝 Communities</button>
      <button class="sec" onclick="prCall('crisis')">🚨 Crisis plan</button>
      <button class="sec" onclick="prCall('strategy')">📝 Strategy doc</button>
      <button onclick="prCall('full')">⚡ FULL PR package</button>
      <button class="sec" onclick="refreshToken()">🔑 Refresh IG token</button>
    </div>
    <pre id="prOut"></pre>
  </div>
  <div class="card" id="companyCard" style="display:none">
    <h3>🏢 Company — CEO + co-workers, works like a real company</h3>
    <label>Give the CEO a goal (e.g. grow Celebrity Gossip, launch gaming content, handle crisis about X)</label>
    <input id="coGoal" placeholder="grow Celebrity Gossip account">
    <button onclick="runCompany()">▶ CEO: run the company</button>
    <pre id="coOut"></pre>
  </div>
  <div class="card" id="fleetCard" style="display:none">
    <h3>💻 Fleet — every agent on its own laptop</h3>
    <div class="sub">Each pane is one agent's machine: live status, last run, permissions.</div>
    <div class="laptops" id="laptopGrid"></div>
    <h3 style="margin-top:14px">Live event feed</h3>
    <pre id="fleetEvents"></pre>
    <div class="qbtns">
      <button class="sec" onclick="runCanary()">🩺 Run canary (selector health)</button>
    </div>
  </div>
  <div class="card" id="calCard" style="display:none">
    <h3>📅 Calendar — scheduled posts</h3>
    <div class="sub">Drag a date = reschedule (updates one row — scheduler stays the source of truth).</div>
    <div id="calList"></div>
    <h3 style="margin-top:14px">Reschedule a post</h3>
    <div class="row">
      <div style="flex:1"><label>Post id</label><input id="rsId" type="number"></div>
      <div style="flex:1"><label>New date/time (YYYY-MM-DD HH:MM)</label><input id="rsWhen"></div>
    </div>
    <button class="sec" onclick="reschedulePost()">Move</button>
  </div>
  <div class="card" id="compCard" style="display:none">
    <h3>🥊 Competitor tracking</h3>
    <label>Handles (comma separated, e.g. @rival1, @rival2)</label>
    <input id="cHandles" placeholder="@rival1, @rival2">
    <div class="row">
      <div style="flex:1"><label>Platform</label><select id="cPlatform"><option>instagram</option><option>tiktok</option><option>threads</option></select></div>
    </div>
    <div class="qbtns">
      <button onclick="cronCompetitors()">📸 Snapshot now (job queue)</button>
      <button class="sec" onclick="listCompetitors()">📊 View tracked + growth</button>
    </div>
    <pre id="compOut"></pre>
  </div>
  <div class="card" id="inboxCard" style="display:none">
    <h3>📥 Unified Inbox — DMs, comments, mentions in one place</h3>
    <div class="sub">Fetch via the visible browser (frontend path — no token needed). Reply agent writes in the account's voice.</div>
    <div class="row">
      <div style="flex:1"><label>Instagram account (fetch its notifications)</label><select id="inAcct"></select></div>
      <div style="flex:1"><label>Filter status</label><select id="inFilter" onchange="loadInbox()"><option value="">all</option><option value="unread">unread</option><option value="replied">replied</option></select></div>
    </div>
    <div class="qbtns">
      <button onclick="fetchInbox()">📬 Fetch via browser</button>
      <button class="sec" onclick="loadInbox()">🔄 Refresh inbox</button>
    </div>
    <div id="inboxList"></div>
    <h3 style="margin-top:14px">Reply agent</h3>
    <label>Inbox item id + post URL (for the reply)</label>
    <div class="row">
      <div style="flex:1"><input id="rpItem" type="number" placeholder="item id"></div>
      <div style="flex:2"><input id="rpUrl" placeholder="post URL"></div>
    </div>
    <div class="qbtns">
      <button class="sec" onclick="genReply()">✍️ Generate reply (voice + reviewer)</button>
      <button onclick="postReply()">💬 Reply via browser</button>
    </div>
    <pre id="rpOut"></pre>
  </div>
  <div class="card" id="growthCard" style="display:none">
    <h3>♻️ Growth loop — repurpose, ideas, weekly report, feedback</h3>
    <h3 style="margin-top:4px;font-size:13px">1. Content repurposing</h3>
    <label>Long video (picked file or path) → auto-cut shorts + captions + thread + carousel, auto-posted</label>
    <div class="row">
      <div style="flex:2"><input id="grVideo" placeholder="path to long video (or pick in Create Post first)"></div>
    </div>
    <div class="qbtns">
      <button onclick="repurpose(false)">♻️ Repurpose + auto-post</button>
      <button class="sec" onclick="repurpose(true)">🧪 Dry run</button>
    </div>
    <h3 style="margin-top:10px;font-size:13px">2. Trend-to-content ideas</h3>
    <div class="row"><div style="flex:2"><input id="grTopic" placeholder="topic (optional — uses your niche data)"></div></div>
    <div class="qbtns"><button class="sec" onclick="getIdeas()">💡 Propose 5 hooks</button></div>
    <h3 style="margin-top:10px;font-size:13px">3. Weekly CEO report</h3>
    <div class="qbtns">
      <button class="sec" onclick="weeklyReport()">📄 Generate report</button>
      <button class="sec" onclick="weeklyReport(true)">📤 Send to Telegram</button>
    </div>
    <h3 style="margin-top:10px;font-size:13px">4. Feedback loop (24h/7d lessons)</h3>
    <div class="qbtns">
      <button class="sec" onclick="runFeedback(24)">⏱️ Score 24h-old posts</button>
      <button class="sec" onclick="runFeedback(168)">📅 Score 7d-old posts</button>
    </div>
    <pre id="grOut"></pre>
  </div>
</div>
<script>
const P = {
  instagram:{label:'Instagram',fields:[['name','Account name (label)'],['description','Description (e.g. celebrity gossip)'],['link','Profile link (opens in browser)'],['ig_user_id','IG User ID (API)'],['graph_token','Long-lived Graph token (API)'],['username','Instagram username (browser)'],['password','Instagram password (browser only)']],types:['reels','video','post','story']},
  x:{label:'X (Twitter)',fields:[['name','Account name'],['username','X username (free via twikit)'],['password','X password (free via twikit)'],['bearer_token','Bearer token (official API, paid)']],types:['text']},
  linkedin:{label:'LinkedIn',fields:[['name','Account name'],['access_token','Access token'],['organization_urn','Organization URN']],types:['text']},
  youtube:{label:'YouTube',fields:[['name','Account name'],['token_file','OAuth token file path']],types:['shorts','video']},
  facebook:{label:'Facebook',fields:[['name','Account name (label)'],['description','Description'],['link','Page link (opens in browser)'],['page_id','Page ID (API)'],['page_token','Page token (API)'],['username','Facebook email (browser)'],['password','Facebook password (browser only)']],types:['video']},
};
let cur='instagram';
async function api(path,method='GET',body){
  const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  return r.json();
}
function refreshNav(){document.querySelectorAll('.nav a').forEach(a=>{a.classList.toggle('on',a.dataset.p===cur);
  document.getElementById('seoCard').style.display=cur==='seo'?'block':'none';
  document.getElementById('cmtCard').style.display=cur==='comments'?'block':'none';
  document.getElementById('taskCard').style.display=cur==='tasks'?'block':'none';
  document.getElementById('learnCard').style.display=cur==='learn'?'block':'none';
  document.getElementById('prCard').style.display=cur==='pr'?'block':'none';
  document.getElementById('companyCard').style.display=cur==='company'?'block':'none';
  document.getElementById('fleetCard').style.display=cur==='fleet'?'block':'none';
  document.getElementById('calCard').style.display=cur==='calendar'?'block':'none';
  document.getElementById('compCard').style.display=cur==='competitors'?'block':'none';
  document.getElementById('inboxCard').style.display=cur==='inbox'?'block':'none';
  document.getElementById('growthCard').style.display=cur==='growth'?'block':'none';
  const hideAll=(cur==='seo'||cur==='comments'||cur==='tasks'||cur==='learn'||cur==='pr'||cur==='company'||cur==='fleet'||cur==='calendar'||cur==='competitors'||cur==='inbox'||cur==='growth');
  document.getElementById('acctCard').style.display=hideAll?'none':'block';
  document.querySelector('.main .card:nth-of-type(2)').style.display=hideAll?'none':'block';});
  if(cur==='fleet'){loadFleet();}
  if(cur==='calendar'){loadCalendar();}
  if(cur==='inbox'){fillInboxAccts();loadInbox();}
  if(P[cur]){renderAcct();fillMultiAccts();}}
document.querySelectorAll('.nav a').forEach(a=>a.onclick=()=>{cur=a.dataset.p;refreshNav();});
async function renderAcct(){
  const pl=P[cur]; if(!pl)return;
  document.getElementById('platTitle').textContent=pl.label+' accounts';
  const data=await api('/api/accounts');
  const list=(data[cur]||[]);
  document.getElementById('acctList').innerHTML=list.length?list.map(a=>
    `<div class="acct"><div><b>${a.name||a._id}</b> <span class="badge">${a._id}</span>${a.description?`<div style="font-size:12px;color:#9aa0a8">${a.description}</div>`:''}</div><div><button class="sec" onclick="openAcct('${cur}','${a._id}')">Open</button> <button class="sec" onclick="editAcct('${cur}','${a._id}')">Edit</button> <button class="sec" onclick="del('${cur}','${a._id}')">Remove</button></div></div>`).join(''):'<div class="badge">No accounts yet</div>';
  document.getElementById('addForm').innerHTML='<h3 style="margin-top:14px">Add '+pl.label+' account</h3>'+
    pl.fields.map(f=>`<label>${f[1]}</label><input id="f_${f[0]}">`).join('')+
    `<button onclick="add()">Add account</button>`;
  document.getElementById('pPlatform').innerHTML=Object.keys(P).map(k=>`<option ${k===cur?'selected':''}>${k}</option>`).join('');
  refreshAccounts();
}
async function refreshAccounts(){
  const pl=document.getElementById('pPlatform').value;const data=await api('/api/accounts');
  const list=(data[pl]||[]);
  document.getElementById('pAccount').innerHTML=list.map(a=>`<option value="${a._id}">${a.name||a._id}</option>`).join('')||'<option value="">— add an account —</option>';
  document.getElementById('pType').innerHTML=P[pl].types.map(t=>`<option>${t}</option>`).join('');
}
async function add(){const pl=P[cur];const o={};pl.fields.forEach(f=>o[f[0]]=document.getElementById('f_'+f[0]).value);
  await api('/api/accounts','POST',{platform:cur,account:o});renderAcct();}
async function del(pl,uid){await api('/api/accounts/delete','POST',{platform:pl,uid});renderAcct();}
async function openAcct(pl,uid){const r=await api('/api/open-account','POST',{platform:pl,uid});alert(r.ok?('Opening: '+r.url):('Error: '+r.error));}
async function editAcct(pl,uid){const data=await api('/api/accounts');const a=(data[pl]||[]).find(x=>x._id===uid)||{};const f=prompt('Edit name / description / link (JSON):',JSON.stringify({name:a.name||'',description:a.description||'',link:a.link||''},null,2));if(!f)return;try{const o=JSON.parse(f);await api('/api/accounts/edit','POST',{platform:pl,uid,...o});renderAcct();}catch(e){alert('Invalid JSON');}}
async function seo(){document.getElementById('pDesc').value='';const r=await api('/api/seo','POST',{platform:document.getElementById('pPlatform').value,title:document.getElementById('pTitle').value,description:document.getElementById('pDesc').value||document.getElementById('pTitle').value});
  document.getElementById('pTitle').value=r.title;document.getElementById('pDesc').value=r.description;document.getElementById('postOut').textContent='SEO applied ✓';}
async function post(){const r=await api('/api/post','POST',{platform:document.getElementById('pPlatform').value,account_id:document.getElementById('pAccount').value,media_type:document.getElementById('pType').value,title:document.getElementById('pTitle').value,description:document.getElementById('pDesc').value,file:document.getElementById('pFile').value,publish_at:document.getElementById('pWhen').value||null});
  document.getElementById('postOut').textContent=JSON.stringify(r,null,2);}
async function postBrowser(){const r=await api('/api/post-browser','POST',{platform:document.getElementById('pPlatform').value,account_id:document.getElementById('pAccount').value,media_type:document.getElementById('pType').value,title:document.getElementById('pTitle').value,description:document.getElementById('pDesc').value,file:document.getElementById('pFile').value});
  document.getElementById('postOut').textContent=JSON.stringify(r,null,2)+'\n\nA visible browser should open — complete login/2FA and the final Share there.';}
async function uploadFile(){const f=document.getElementById('pFilePick').files[0];if(!f)return;
  const fd=new FormData();fd.append('file',f);
  document.getElementById('pFileInfo').textContent='Uploading & analyzing '+f.name+'...';
  try{const resp=await fetch('/api/upload',{method:'POST',body:fd});const r=await resp.json();
  if(r.ok){document.getElementById('pFile').value=r.file;
    const plat=document.getElementById('pPlatform').value;
    const want=plat==='youtube'?r.suggested_yt:r.suggested_type;
    document.getElementById('pFileInfo').textContent='✓ '+r.duration+'s · '+r.width+'x'+r.height+' · '+r.codec+' · '+(r.vertical?'vertical':'horizontal')+' → type: '+want;
    const t=document.getElementById('pType');
    if([...t.options].some(o=>o.value===want))t.value=want;
    if(!document.getElementById('pTitle').value){await seoFromRaw(f.name.replace(/\.[^.]+$/,''));}
  }else{document.getElementById('pFileInfo').textContent='Error: '+(r.error||'upload failed');}}
  catch(e){document.getElementById('pFileInfo').textContent='Upload failed: '+e.message;}}
async function seoFromRaw(raw){const r=await api('/api/seo','POST',{platform:document.getElementById('pPlatform').value,title:raw,description:raw});
  document.getElementById('pTitle').value=r.title;document.getElementById('pDesc').value=r.description;}
async function fillCommentAccts(){const plat=document.getElementById('mPlat').value;const data=await api('/api/accounts');const list=(data[plat]||[]).filter(a=>a.username);
  document.getElementById('bAcct').innerHTML=list.map(a=>`<option value="${a._id}">${a.name||a._id} (${a.username})</option>`).join('')||`<option value="">— no browser accounts (add username+password to a ${plat} account) —</option>`;}
async function fillLearnAccts(){const data=await api('/api/accounts');const list=(data.instagram||[]).filter(a=>a.username);
  document.getElementById('lAcct').innerHTML='<option value="">— none —</option>'+list.map(a=>`<option value="${a._id}">${a.name||a._id} (${a.username})</option>`).join('');}
async function multiAction(mode){const sel=document.getElementById('bAcct');const ids=[...sel.selectedOptions].map(o=>o.value);const plat=document.getElementById('mPlat').value;
  if(!ids.length){document.getElementById('bOut').textContent='Select at least one account (Ctrl+click).';return;}
  const body=mode==='watch'?{platform:plat,url:document.getElementById('bUrl').value,account_ids:ids}:{platform:plat,url:document.getElementById('bUrl').value,account_ids:ids,idea:document.getElementById('bText').value};
  const r=await api(mode==='watch'?'/api/watch-multi':'/api/comment-multi','POST',body);
  document.getElementById('bOut').textContent=JSON.stringify(r,null,2);}
async function learnReel(){const aid=document.getElementById('lAcct').value;let creds={};
  if(aid){const data=await api('/api/accounts');const a=(data.instagram||[]).find(x=>x._id===aid)||{};creds={username:a.username,password:a.password};}
  const r=await api('/api/learn-reel','POST',{url:document.getElementById('lUrl').value,save_tags:document.getElementById('lSave').checked,...creds});
  const o=r.ok?`Hashtags: ${(r.hashtags||[]).map(h=>'#'+h).join(' ')}\nCounts: ${JSON.stringify(r.counts)}\n\nInsights:\n${(r.insights||[]).map(i=>'- '+i).join('\n')}`:JSON.stringify(r,null,2);
  document.getElementById('learnOut').textContent=o;}
async function prCall(which){const topic=document.getElementById('prTopic').value;
  document.getElementById('prOut').textContent='Running '+which+'... (full package takes ~30s)';
  try{const r=await api('/api/pr/'+which,'POST',{topic});document.getElementById('prOut').textContent=JSON.stringify(r,null,2);}
  catch(e){document.getElementById('prOut').textContent='Error: '+e.message;}}
async function refreshToken(){document.getElementById('prOut').textContent='Refreshing token...';
  const r=await api('/api/refresh-token','POST',{});document.getElementById('prOut').textContent=JSON.stringify(r,null,2);}
async function runCompany(){const goal=document.getElementById('coGoal').value;
  document.getElementById('coOut').textContent='CEO delegating to co-workers... (~30s)';
  try{const r=await api('/api/company','POST',{goal});
  const o=r.decision+'\n\nACTION ITEMS:\n'+r.action_items.join('\n')+'\n\n=== WORKERS REPORTS ===\n'+r.workers_reports.map(w=>'\n'+w.worker+' — '+w.task+'\n  '+w.summary).join('\n');
  document.getElementById('coOut').textContent=o;}
  catch(e){document.getElementById('coOut').textContent='Error: '+e.message;}}
async function runTask(){const t=document.getElementById('tInput').value;
  if(!t.trim()){document.getElementById('taskOut').textContent='Type a task first (or touch a quick button).';return;}
  document.getElementById('taskOut').textContent='Agents working on it... (~1-2 min)';
  try{const r=await api('/api/task','POST',{task:t});
  const o=r.results&&r.results.length?r.results.map((x,i)=>{
    if(x.decision)return '✅ '+x.action.toUpperCase()+': '+x.topic+'\n\n'+x.decision+'\n\nACTION ITEMS:\n'+(x.action_items||[]).join('\n')+'\n\nWORKERS:\n'+(x.workers_reports||[]).map(w=>'  '+w.worker+': '+w.summary).join('\n');
    return (i+1)+'. '+JSON.stringify(x);}).join('\n\n'):('No actions parsed.');
  document.getElementById('taskOut').textContent=o;}
  catch(e){document.getElementById('taskOut').textContent='Error: '+e.message;}}
async function quickTask(prefix){const inp=document.getElementById('tInput');
  inp.value=prefix;inp.focus();
  if(prefix==='analytics'){runTask();}}
document.getElementById('tInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();runTask();}});
async function loadStatus(){try{const d=await api('/api/accounts');
  const n=Object.values(d).reduce((s,l)=>s+(l||[]).length,0);
  document.getElementById('stAccts').textContent='Accounts: '+n;
  const r=await api('/api/llm-status');
  document.getElementById('stLlm').textContent=r.ok?('LLM: '+r.model.split('/').pop()+' ✓'):('LLM: offline (templates)');
  document.getElementById('stLlm').className='chip '+(r.ok?'ok':'warn');}catch(e){}}
async function loadFleet(){const r=await api('/api/fleet');
  document.getElementById('laptopGrid').innerHTML=(r.laptops||[]).map(l=>
    `<div class="laptop"><div class="screen"><div class="name">${l.agent}<span class="dot ${l.status}"></span></div><div class="meta">${l.role}<br>Permissions: ${l.permissions}<br>Runs: ${l.runs}<br>Last: ${l.last_run}</div></div><div class="base"></div></div>`).join('');
  document.getElementById('fleetEvents').textContent=(r.events||[]).map(e=>e.created_at+' ['+e.kind+'] '+e.detail).join('\n')||'(no events yet)';}
async function loadCalendar(){const r=await api('/api/calendar');
  document.getElementById('calList').innerHTML=(r.scheduled||[]).map(s=>
    `<div class="acct"><div><b>${s.title||s.id}</b> <span class="badge">${s.platform}</span><div style="font-size:12px;color:#9aa0a8">${s.scheduled_at} · status: ${s.status}</div></div><button class="sec" onclick="document.getElementById('rsId').value=${s.id};document.getElementById('rsWhen').value='${s.scheduled_at}';document.getElementById('rsWhen').focus()">Pick</button></div>`).join('')||'<div class="badge">Nothing scheduled — queue posts with a date first</div>';}
async function reschedulePost(){const r=await api('/api/reschedule','POST',{post_id:+document.getElementById('rsId').value,scheduled_at:document.getElementById('rsWhen').value});
  alert(r.ok?'Moved ✓':'Error');loadCalendar();}
async function runCanary(){const r=await api('/api/canary','POST',{});
  document.getElementById('fleetEvents').textContent+= '\n\nCANARY:\n'+r.checks.map(c=>c.flow+': '+c.status).join('\n');}
async function cronCompetitors(){const r=await api('/api/competitor-cron','POST',{handles_str:document.getElementById('cHandles').value,platform:document.getElementById('cPlatform').value});
  document.getElementById('compOut').textContent=JSON.stringify(r,null,2);}
async function listCompetitors(){const r=await api('/api/competitors');
  const o=(r.competitors||[]).map(c=>c.handle+' ('+c.platform+'): followers='+c.followers+' posts='+c.posts+' seen='+c.last_seen).join('\n')||'(none tracked yet)';
  document.getElementById('compOut').textContent=o;}
async function fillInboxAccts(){const data=await api('/api/accounts');const list=(data.instagram||[]).filter(a=>a.username);
  document.getElementById('inAcct').innerHTML=list.map(a=>`<option value="${a._id}">${a.name||a._id} (${a.username})</option>`).join('')||'<option value="">— no browser accounts —</option>';}
async function fetchInbox(){const r=await api('/api/inbox-fetch','POST',{account_id:document.getElementById('inAcct').value,platform:'instagram'});
  document.getElementById('rpOut').textContent=JSON.stringify(r,null,2);if(r.ok)loadInbox();}
async function loadInbox(){const f=document.getElementById('inFilter').value;const r=await api('/api/inbox','POST',{status:f});
  document.getElementById('inboxList').innerHTML=(r.inbox||[]).map(i=>
    `<div class="acct"><div><b>${i.kind}</b> from ${i.from_user} <span class="badge">${i.status}</span><div style="font-size:12px;color:#9aa0a8">${(i.text||'').substring(0,120)}</div></div><button class="sec" onclick="document.getElementById('rpItem').value=${i.id};document.getElementById('rpUrl').value='${i.url||''}';document.getElementById('rpUrl').focus()">Reply to</button></div>`).join('')||'<div class="badge">Inbox empty — Fetch via browser first</div>';}
async function genReply(){const r=await api('/api/inbox-reply','POST',{item_id:+document.getElementById('rpItem').value,account_id:document.getElementById('inAcct').value,url:document.getElementById('rpUrl').value,browser:false});
  document.getElementById('rpOut').textContent=JSON.stringify(r,null,2);}
async function postReply(){const r=await api('/api/inbox-reply','POST',{item_id:+document.getElementById('rpItem').value,account_id:document.getElementById('inAcct').value,url:document.getElementById('rpUrl').value,browser:true});
  document.getElementById('rpOut').textContent=JSON.stringify(r,null,2);if(r.ok)loadInbox();}
async function repurpose(dry){const r=await api('/api/repurpose','POST',{video:document.getElementById('grVideo').value,dry_run:dry});
  const o=r.ok?`${dry?'DRY RUN — nothing posted.':'POSTED to job queue.'}\nDuration: ${r.duration}s\nCuts: ${(r.cuts||[]).length}\nThread:\n${r.assets.thread}\nQuote card: ${r.assets.quote_card}\nQueued: ${(r.queued_posts||[]).map(p=>p.cut+' -> '+p.account+' (#'+p.job_id+')').join('\n')||'(dry run)'}`:JSON.stringify(r,null,2);
  document.getElementById('grOut').textContent=o;}
async function getIdeas(){const r=await api('/api/ideas','POST',{topic:document.getElementById('grTopic').value});
  const o=r.ok?`IDEAS:\n${r.hooks.map((h,i)=>(i+1)+'. '+h).join('\n')}\n\nRising hashtags: ${r.rising_hashtags.map(t=>'#'+t).join(' ')}\nCompetitors: ${r.competitors.join(', ')}`:JSON.stringify(r,null,2);
  document.getElementById('grOut').textContent=o;}
async function weeklyReport(send){const r=await api('/api/weekly','POST',{send_to:send?'telegram':''});
  document.getElementById('grOut').textContent=r.report+(r.sent?'\n\nSent via '+r.sent.via:'')+'\n\n'+(r.sent&&r.sent.note?r.sent.note:'');}
async function runFeedback(h){const r=await api('/api/feedback','POST',{hours:h});
  const o=r.ok?`BASELINE: ${r.baseline} views\n\n${(r.lessons||[]).map(l=>l.title+': '+l.views+' views — '+l.verdict+(l.winning_tags.length?' | winning: #'+l.winning_tags.join(' #'):'')).join('\n')||r.note}`:JSON.stringify(r,null,2);
  document.getElementById('grOut').textContent=o;}
async function runSeo(){const r=await api('/api/seo','POST',{platform:document.getElementById('seoPlat').value,title:document.getElementById('seoTitle').value,description:document.getElementById('seoDesc').value});
  document.getElementById('seoOut').textContent=JSON.stringify(r,null,2);}
async function genreTrends(){const r=await api('/api/genre-trends','POST',{genre:document.getElementById('gGenre').value});
  const o=r.ok?`Genre tags: ${(r.genre_tags||[]).map(t=>'#'+t).join(' ')}\n\nTrending NOW: ${r.trending_now.join(', ')}\n\nHeadlines:\n${(r.news_headlines||[]).map(h=>'- '+h).join('\n')}`:JSON.stringify(r,null,2);
  document.getElementById('gOut').textContent=o;}
async function fillMultiAccts(){const data=await api('/api/accounts');const plat=document.getElementById('pPlatform').value;const list=(data[plat]||[]).filter(a=>a.username);
  document.getElementById('mpAccounts').innerHTML=list.map(a=>`<label style="display:block;font-size:13px;margin:3px 0"><input type="checkbox" class="mpAcct" value="${a._id}" style="width:auto"> ${a.name||a._id} <span class="badge">${a.username}</span></label>`).join('')||'<div class="badge">— no browser accounts —</div>';}
async function multiPost(){const ids=[...document.querySelectorAll('.mpAcct:checked')].map(c=>c.value);
  if(!ids.length){document.getElementById('mpOut').textContent='Tick at least one account checkbox.';return;}
  const r=await api('/api/post-multi','POST',{platform:document.getElementById('pPlatform').value,account_ids:ids,file:document.getElementById('pFile').value,title:document.getElementById('mpTitle').value,media_type:document.getElementById('pType').value});
  document.getElementById('mpOut').textContent=JSON.stringify(r,null,2);}
async function genComments(){const r=await api('/api/comments','POST',{idea:document.getElementById('cIdea').value,count:+document.getElementById('cCount').value});
  document.getElementById('cmtOut').textContent=r.comments.map((c,i)=>(i+1)+'. '+c).join('\n');}
async function postComments(){const r=await api('/api/comments/post','POST',{comments:document.getElementById('cmtOut').textContent.split('\n').map(l=>l.replace(/^\d+\.\s*/,'')),accounts:document.getElementById('cTargets').value.split(',').map(s=>s.trim()).filter(Boolean)});
  document.getElementById('cmtOut').textContent+='\n\n'+JSON.stringify(r,null,2);}
refreshNav();
loadStatus();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML, "text/html")
        elif self.path == "/api/accounts":
            self._send(200, json.dumps(accounts()))
        elif self.path == "/api/health":
            self._send(200, json.dumps({"ok": True}))
        elif self.path == "/api/jobs":
            import job_runner, hubdb
            self._send(200, json.dumps({"jobs": hubdb.list_jobs()}))
        elif self.path == "/api/llm-status":
            import llm
            if llm.API_KEY:
                out = llm.chat("Say OK", max_tokens=100, timeout=30)
                self._send(200, json.dumps({"ok": bool(out),
                                              "model": llm.MODEL}))
            else:
                self._send(200, json.dumps({"ok": False,
                                              "model": "none"}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        if self.path == "/api/upload":
            ctype = self.headers.get("Content-Type", "")
            if "multipart" not in ctype:
                self._send(400, json.dumps(
                    {"ok": False, "error": "expected multipart form-data"}))
                return
            try:
                payload = _parse_multipart(ctype, raw)
            except Exception as e:
                self._send(400, json.dumps(
                    {"ok": False, "error": f"bad multipart: {e}"}))
                return
            try:
                self._send(200, json.dumps(do_upload(payload)))
            except Exception as e:
                self._send(500, json.dumps(
                    {"ok": False, "error": f"{type(e).__name__}: {e}"}))
            return
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            payload = {}
        routes = {
            "/api/accounts": lambda: add_account(
                payload.get("platform", ""),
                payload.get("account", {})),
            "/api/accounts/delete": lambda: (
                remove_account(payload.get("platform", ""),
                               payload.get("uid", "")),
                {"ok": True})[1],
            "/api/seo": lambda: do_seo(payload),
            "/api/comments": lambda: do_gen_comments(payload),
            "/api/comments/post": lambda: do_post_comments(payload),
            "/api/post-browser": lambda: do_post_browser(payload),
            "/api/comment-browser": lambda: do_comment_browser(payload),
            "/api/accounts/edit": lambda: do_edit_account(payload),
            "/api/open-account": lambda: do_open_account(payload),
            "/api/task": lambda: do_task(payload),
            "/api/jobs/cancel": lambda: _cancel_job(payload),
            "/api/migrate": lambda: do_migrate(payload),
            "/api/fleet": lambda: _fleet(),
            "/api/calendar": lambda: _calendar(),
            "/api/reschedule": lambda: _reschedule(payload),
            "/api/canary": lambda: _canary(),
            "/api/competitors": lambda: _competitors(),
            "/api/competitor-cron": lambda: _competitor_cron(payload),
            "/api/inbox": lambda: _inbox(payload),
            "/api/inbox-fetch": lambda: _inbox_fetch(payload),
            "/api/inbox-reply": lambda: _inbox_reply(payload),
            "/api/repurpose": lambda: _repurpose(payload),
            "/api/ideas": lambda: _ideas(payload),
            "/api/weekly": lambda: _weekly(payload),
            "/api/feedback": lambda: _feedback(payload),
            "/api/watch-multi": lambda: do_watch_multi(payload),
            "/api/comment-multi": lambda: do_comment_multi(payload),
            "/api/post-multi": lambda: do_post_multi(payload),
            "/api/genre-trends": lambda: do_genre_trends(payload),
            "/api/learn-reel": lambda: do_learn_reel(payload),
            "/api/pr/analytics": lambda: pr_analytics(),
            "/api/refresh-token": lambda: do_refresh_token(payload),
            "/api/pr/monitor": lambda: pr_monitor(payload),
            "/api/pr/crisis": lambda: pr_crisis(payload),
            "/api/pr/strategy": lambda: pr_strategy(payload),
            "/api/pr/full": lambda: pr_full(payload),
            "/api/company": lambda: company_run(payload),
            "/api/post": lambda: do_post(payload),
        }
        handler = routes.get(self.path)
        if not handler:
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            self._send(200, json.dumps(handler()))
        except Exception as e:
            self._send(500, json.dumps(
                {"ok": False, "error": f"{type(e).__name__}: {e}"}))
        else:
            self._send(404, json.dumps({"error": "not found"}))


def main():
    # localhost only — the dashboard holds credentials; never expose
    # it to the LAN
    import job_runner, hubdb
    job_runner.start()
    n = hubdb.migrate_accounts_from_json()
    server = ThreadingHTTPServer(("127.0.0.1", 8090), Handler)
    print("SocialHub dashboard -> http://localhost:8090")
    print(f"Job runner started. Accounts migrated: {n}")
    server.serve_forever()


if __name__ == "__main__":
    main()
