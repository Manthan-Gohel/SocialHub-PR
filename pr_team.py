"""PR Team engine — full agentic PR stack for the dashboard.

Roles (each is a function the dashboard calls):
  Analyst        → real analytics: IG insights, YT stats, FB page stats
  Research       → mentions + sentiment across Reddit (live JSON API)
  Media Handler  → crisis response plan, press release, sample posts
  Content Writer → sample tweets/posts, press release drafts
  Community Mgr  → finds communities/threads discussing a topic
  Manager        → strategy doc + full_package() orchestration

Free/real sources: Instagram Graph insights, YouTube Data API stats,
Reddit public search JSON (no auth). Discord needs a bot token (note).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
sys_path = str(BASE)

UA = {"User-Agent": "Mozilla/5.0 SocialHub-PR/1.0 (research bot)"}

POSITIVE = ["love", "great", "amazing", "best", "good", "awesome",
            "beautiful", "win", "happy", "gorgeous", "iconic",
            "stunning", "legend", "king", "queen", "respect"]
NEGATIVE = ["hate", "bad", "worst", "awful", "fake", "scandal",
            "crisis", "cancel", "canceled", "boycott", "ugly", "toxic",
            "drama", "cheat", "cheated", "lie", "liar", "angry",
            "outrage", "exposed", "fraud", "arrest", "lawsuit"]


# ---------------- Sentiment (keyword-based, no LLM needed) ----------------
def sentiment(text: str) -> dict:
    low = (text or "").lower()
    pos = sum(1 for w in POSITIVE if w in low)
    neg = sum(1 for w in NEGATIVE if w in low)
    total = pos + neg
    label = "neutral" if total == 0 else (
        "positive" if pos > neg else "negative")
    score = 0 if total == 0 else round((pos - neg) / total, 2)
    return {"label": label, "score": score, "pos": pos, "neg": neg}


# ---------------- Analyst: REAL analytics ----------------
def ig_analytics(acct: dict) -> dict:
    """Real Instagram analytics. Graph API first; browser fallback
    when the token is expired/missing (scrapes public profile)."""
    ig_id, token = acct.get("ig_user_id"), acct.get("graph_token")
    if not ig_id or not token:
        return ig_analytics_browser(acct, "no API token — browser fallback")
    out = {"platform": "instagram", "name": acct.get("name"), "ok": True}
    try:
        r = requests.get(
            f"https://graph.facebook.com/v21.0/{ig_id}",
            params={"fields": "followers_count,media_count",
                    "access_token": token}, timeout=30)
        r.raise_for_status()
        j = r.json()
        out["followers"] = j.get("followers_count")
        out["posts"] = j.get("media_count")
    except Exception as e:
        # token expired/invalid → browser fallback
        return ig_analytics_browser(acct,
                                      f"token failed ({str(e)[:60]}) — "
                                      "browser fallback")
    try:
        r = requests.get(
            f"https://graph.facebook.com/v21.0/{ig_id}/insights",
            params={"metric": "impressions,reach,profile_views",
                    "period": "days_28", "access_token": token}, timeout=30)
        j = r.json()
        if "data" in j:
            for line in j["data"]:
                vals = line.get("values", [])
                out[line["name"]] = vals[-1].get("value") if vals else None
    except Exception:
        pass  # insights need 28d history; fine
    return out


def ig_analytics_browser(acct: dict, note: str = "") -> dict:
    """Scrape the public profile page (no login needed) — works when
    the Graph token is expired: followers/following/posts from the
    page's og:description metadata."""
    from playwright.sync_api import sync_playwright
    import re
    user = acct.get("username") or (acct.get("link") or "").rstrip("/").rsplit("/", 1)[-1].lstrip("@")
    if not user:
        return {"platform": "instagram", "name": acct.get("name"),
                "ok": False, "error": "no username for browser fallback"}
    out = {"platform": "instagram", "name": acct.get("name"),
           "mode": "browser", "ok": True}
    if note:
        out["note"] = note
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            pg = browser.new_context(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36")).new_page()
            pg.goto(f"https://www.instagram.com/{user}/",
                      wait_until="domcontentloaded", timeout=45_000)
            pg.wait_for_timeout(4_000)
            html = pg.content()
            m = re.search(r'property="og:description" content="([^"]*)"',
                          html)
            desc = m.group(1) if m else ""
            fm = re.search(r"([\d.,]+)\s*Followers", desc, re.I)
            fg = re.search(r"([\d.,]+)\s*Following", desc, re.I)
            fp = re.search(r"([\d.,]+)\s*Posts", desc, re.I)
            out["followers"] = _parse_count(fm.group(1)) if fm else None
            out["following"] = _parse_count(fg.group(1)) if fg else None
            out["posts"] = _parse_count(fp.group(1)) if fp else None
            if out["followers"] is None:
                out["ok"] = False
                out["error"] = "profile page showed no counts " \
                               "(login wall or blocked)"
        except Exception as e:
            out["ok"] = False
            out["error"] = str(e)[:150]
        finally:
            browser.close()
    return out


def _parse_count(s: str) -> int | None:
    s = s.strip().replace(",", "")
    if s.endswith("K") or s.endswith("M"):
        mult = 1_000 if s.endswith("K") else 1_000_000
        try:
            return int(float(s[:-1]) * mult)
        except ValueError:
            return None
    try:
        return int(float(s))
    except ValueError:
        return None


def yt_analytics() -> dict:
    """Real YouTube channel stats via the existing OAuth token.json."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except Exception as e:
        return {"platform": "youtube", "ok": False, "error": str(e)[:200]}
    tok = BASE / "token.json"
    if not tok.exists():
        return {"platform": "youtube", "ok": False,
                "error": "token.json missing — run upload_youtube once"}
    try:
        creds = Credentials.from_authorized_user_file(str(tok), [
            "https://www.googleapis.com/auth/youtube.force-ssl"])
        yt = build("youtube", "v3", credentials=creds)
        ch = yt.channels().list(mine=True, part="snippet,statistics").execute()
        items = ch.get("items", [])
        if not items:
            return {"platform": "youtube", "ok": False,
                    "error": "no channel for this token"}
        s = items[0]["statistics"]
        return {"platform": "youtube", "ok": True,
                "name": items[0]["snippet"].get("title"),
                "subscribers": s.get("subscriberCount"),
                "views": s.get("viewCount"),
                "videos": s.get("videoCount")}
    except Exception as e:
        return {"platform": "youtube", "ok": False, "error": str(e)[:200]}


def fb_analytics(acct: dict) -> dict:
    """Real Facebook Page stats."""
    pid, token = acct.get("page_id"), acct.get("page_token")
    if not pid or not token:
        return {"platform": "facebook", "ok": False,
                "error": "needs page_id + page_token"}
    try:
        r = requests.get(f"https://graph.facebook.com/v21.0/{pid}",
                         params={"fields": "followers_count,fan_count",
                                 "access_token": token}, timeout=30)
        r.raise_for_status()
        j = r.json()
        return {"platform": "facebook", "ok": True,
                "name": acct.get("name"),
                "followers": j.get("followers_count"),
                "likes": j.get("fan_count")}
    except Exception as e:
        return {"platform": "facebook", "ok": False, "error": str(e)[:200]}


def analytics_snapshot(accounts: dict) -> dict:
    """All platforms' real stats in one call.

    Browser fallback scrapes are slow (~6s each), so at most 3 are
    scraped per call — the rest are marked skipped."""
    out = []
    ig = accounts.get("instagram", [])
    browser_scrapes = 0
    for a in ig:
        if not (a.get("ig_user_id") and a.get("graph_token")):
            # will be a browser scrape (slow) — cap at 3
            browser_scrapes += 1
            if browser_scrapes > 3:
                # ponytail: cap scrapes for speed; token refresh fixes
                out.append({"platform": "instagram",
                              "name": a.get("name"), "ok": False,
                              "error": "skipped (browser scrape cap — "
                                       "paste a fresh token for full "
                                       "analytics)"})
                continue
        r = ig_analytics(a)
        if r.get("mode") == "browser":
            browser_scrapes += 1
        out.append(r)
    yt = yt_analytics()
    if yt.get("ok"):
        out.append(yt)
    for a in accounts.get("facebook", []):
        out.append(fb_analytics(a))
    return {"ok": True, "generated_at": time.strftime("%Y-%m-%d %H:%M"),
            "platforms": out}


# ---------------- Research: mentions + sentiment ----------------
def _news_mentions(topic: str, t: str = "week", limit: int = 20) -> list:
    """Google News RSS — free, no auth, works where Reddit 403s."""
    import xml.etree.ElementTree as ET
    try:
        r = requests.get(
            "https://news.google.com/rss/search",
            params={"q": topic, "hl": "en-US", "gl": "US",
                    "ceid": "US:en"}, headers=UA, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")[:limit]
    except Exception:
        return []
    out = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        source = (it.findtext("source") or "").strip()
        date = (it.findtext("pubDate") or "").strip()
        out.append({"source": source or "news", "title": title[:160],
                      "url": link, "date": date,
                      "sentiment": sentiment(title)["label"]})
    return out


def monitor_mentions(topic: str, sub: str = "all", t: str = "week",
                     limit: int = 20) -> dict:
    """Live mentions + sentiment. Reddit JSON first (works from
    residential IPs); Google News RSS fallback (works everywhere)."""
    mentions = []
    scores = []
    try:
        r = requests.get(
            f"https://www.reddit.com/r/{sub}/search.json",
            params={"q": topic, "sort": "top", "t": t, "limit": limit,
                    "restrict_sr": "on" if sub != "all" else "off"},
            headers=UA, timeout=30)
        r.raise_for_status()
        for c in r.json().get("data", {}).get("children", []):
            d = c.get("data", {})
            title = d.get("title", "")
            s = sentiment(f"{title} {d.get('selftext', '')[:300]}")
            scores.append(s["score"])
            mentions.append({
                "source": f"r/{d.get('subreddit')}",
                "title": title[:160],
                "url": "https://www.reddit.com" + d.get("permalink", ""),
                "score": d.get("score"),
                "sentiment": s["label"],
            })
    except Exception:
        pass  # Reddit 403s from many IPs — fall back to news

    if not mentions:
        mentions = _news_mentions(topic, t, limit)
        scores = [sentiment(m["title"])["score"] for m in mentions]

    n = len(scores)
    pos = sum(1 for s in scores if s > 0)
    neg = sum(1 for s in scores if s < 0)
    avg = round(sum(scores) / n, 2) if n else 0
    summary = (f"{n} mentions found. Sentiment: {pos} positive, "
               f"{neg} negative, {n - pos - neg} neutral "
               f"(avg {avg:+.2f}).") if n else \
        "No mentions found — try a broader topic."
    return {"ok": True, "topic": topic, "summary": summary,
            "mentions": mentions[:20]}


GOSSSIP_SOURCES = [
    ("r/Entertainment", "reddit"), ("r/popculturechat", "reddit"),
    ("r/Fauxmoi", "reddit"), ("r/Deuxmoi", "reddit"),
    ("r/CelebDrama", "reddit"), ("r/instagramreality", "reddit"),
    ("r/youtubedrama", "reddit"), ("r/YouTubers", "reddit"),
]


def find_communities(topic: str) -> dict:
    """Which communities/outlets are talking about this topic now."""
    out = []
    for sub, kind in GOSSSIP_SOURCES:
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/search.json",
                params={"q": topic, "sort": "top", "t": "week",
                        "limit": 3}, headers=UA, timeout=20)
            posts = r.json().get("data", {}).get("children", [])
            if posts:
                out.append({"community": f"r/{sub}", "type": kind,
                              "threads": len(posts),
                              "top": posts[0]["data"].get("title", "")[:140]})
        except Exception:
            continue
    # news fallback: which outlets cover the topic
    news = _news_mentions(topic, limit=10)
    by_source: dict[str, int] = {}
    for m in news:
        by_source[m["source"]] = by_source.get(m["source"], 0) + 1
    for src, n in sorted(by_source.items(), key=lambda kv: -kv[1])[:8]:
        out.append({"community": src, "type": "news outlet",
                      "threads": n, "top": ""})
    out.append({"community": "Discord servers", "type": "discord",
                  "note": "needs a bot token — add DISCORD_BOT_TOKEN to "
                          "scan servers automatically",
                  "threads": 0, "top": ""})
    return {"ok": True, "topic": topic, "communities": out}


# ---------------- Media Handler: crisis + press ----------------
def crisis_plan(topic: str) -> dict:
    """Crisis response plan + press release + sample posts."""
    t = topic.strip() or "the situation"
    plan = f"""CRISIS RESPONSE PLAN — {t}
Generated: {time.strftime('%Y-%m-%d %H:%M')}

PHASE 1 — HOUR 0-2: MONITOR & VERIFY
- Run Monitor on this topic (Reddit + socials): what is being said, where, how fast
- Screenshot/save evidence; do NOT reply to individual users yet
- Freeze scheduled promotional posts (pausing promo during crisis is critical)

PHASE 2 — HOUR 2-6: ACKNOWLEDGE
- Post ONE short acknowledgment: calm, no defensiveness, no over-explaining
- Pin it. Do not delete comments yet.

PHASE 3 — HOUR 6-24: RESPOND
- If claims are false: state facts once, with evidence, then stop repeating
- If claims are true: own it, state the corrective action, apologize once
- Assign ONE spokesperson account (do not respond from multiple accounts)

PHASE 4 — DAY 1-7: RECOVERY
- Resume normal content with positive, value-first posts
- Engage kindly with supporters; ignore bait
- Track sentiment recovery via Monitor (target: back to neutral within 7 days)

PHASE 5 — ONGOING
- Keep monitoring weekly; log what worked in the growth log
"""
    press = f"""PRESS RELEASE (DRAFT)

FOR IMMEDIATE RELEASE

{t.capitalize()} — Official Statement

We are aware of the recent discussion regarding {t}. After careful
review, we want to share the facts directly:

[STATE THE FACTS — 2-3 sentences, neutral tone]

What we are doing about it:
[CORRECTIVE ACTION — 2 sentences]

We thank our community for the continued support and will share
updates here first.

Media contact: [email]
— The Team
"""
    posts = [
        f"We're aware of the conversation around {t}. We're looking "
        "into it and will share facts here first. Thank you for your "
        "patience. 🙏",
        f"To everyone supporting us during {t} — we see you, and we're "
        "grateful. More soon. ❤️",
        f"Facts over rumors: {t} explained in full [link]. No spin, "
        "just the truth.",
    ]
    return {"ok": True, "topic": topic, "plan": plan,
            "press_release": press, "sample_posts": posts}


# ---------------- Content Writer + Manager: strategy doc ----------------
def strategy_doc(topic: str, accounts: dict | None = None) -> dict:
    """Full PR strategy document for a topic/campaign."""
    t = topic.strip() or "the campaign"
    n_ig = len((accounts or {}).get("instagram", []))
    n_yt = len((accounts or {}).get("youtube", []))
    n_fb = len((accounts or {}).get("facebook", []))
    doc = f"""# PR STRATEGY — {t}
Generated: {time.strftime('%Y-%m-%d %H:%M')}

## 1. Objective
Establish a strong, trusted presence around "{t}" across owned
channels, and be first to the conversation when it moves.

## 2. Assets (current)
- Instagram accounts: {n_ig} (labels + descriptions configured in SocialHub)
- YouTube channels: {n_yt}
- Facebook pages: {n_fb}

## 3. Channels & roles
| Channel | Role | Cadence |
|---|---|---|
| Instagram | Reels engine: content-aware SEO, multi-account | 1-2/day per account |
| YouTube | Shorts + long-form; scheduled slots (evening) | 1-2/day |
| Reddit | Community Manager: listen first, then join threads | monitor daily |
| Facebook | Cross-post video + community | 1/day |

## 4. Content plan (first 2 weeks)
- Week 1: 5 reels + 3 shorts on the core topic; run Learn on the top
  competitor reel; save learned hashtags
- Week 2: respond to what moved — Monitor weekly, double down on the
  format/hashtags that got views

## 5. Monitoring & KPIs
- Daily: Monitor mentions + sentiment (target: >60% positive)
- Weekly: Analytics snapshot (IG reach, YT views, follower growth)
- Coverage: number of external threads referencing the topic

## 6. Crisis readiness
- Crisis PR tab generates a response plan, press release and sample
  posts in one click — pause promo, acknowledge fast, respond once.
"""
    return {"ok": True, "topic": topic, "doc": doc}


def full_package(topic: str, accounts: dict | None = None) -> dict:
    """Manager role: run the WHOLE PR team for one topic."""
    return {
        "ok": True,
        "topic": topic,
        "strategy": strategy_doc(topic, accounts),
        "crisis": crisis_plan(topic),
        "monitoring": monitor_mentions(topic),
        "communities": find_communities(topic),
        "analytics": analytics_snapshot(accounts or {}),
    }
