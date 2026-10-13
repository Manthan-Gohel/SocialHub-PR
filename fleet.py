"""Fleet + calendar + canary + competitor cron.

- fleet(): every agent gets its own "laptop" pane — the UI shows each
  agent's live activity (latest runs, status) so you SEE what they do.
- calendar(): thin — list scheduled posts; drag-drop only updates
  scheduled_at on one row (scheduler stays the single source of truth).
- canary(): daily dry-run selector health checks; failures logged to
  the event table the observability UI reads.
- competitor_cron(): snapshot a competitor's public profile through the
  same job queue, per-platform rate limits; growth curves free
  (metrics is time-series).
"""
from __future__ import annotations

import json
import re
import time

import hubdb

AGENTS = [
    {"id": "ceo", "name": "CEO 🎯", "role": "delegates, decides",
     "permissions": "plans; publishes stays human-approved"},
    {"id": "analyst", "name": "Analyst 📊", "role": "real analytics",
     "permissions": "read-only"},
    {"id": "research", "name": "Research 🔍", "role": "mentions+sentiment",
     "permissions": "read-only"},
    {"id": "writer", "name": "Content Writer ✍️", "role": "calendar+posts",
     "permissions": "drafts only"},
    {"id": "media", "name": "Media Handler 🚨", "role": "crisis+press",
     "permissions": "draft-only, NEVER publishes"},
    {"id": "community", "name": "Community Mgr 🤝", "role": "communities",
     "permissions": "engage via human-supervised browser"},
    {"id": "reviewer", "name": "Reviewer 🛡️", "role": "compliance gate",
     "permissions": "blocks anything non-compliant"},
]


def fleet() -> dict:
    """Every agent's laptop: latest runs + live status per agent."""
    with hubdb.conn() as c:
        rows = c.execute("SELECT * FROM agent_runs "
                           "ORDER BY id DESC LIMIT 200").fetchall()
    runs = [dict(r) for r in rows]
    laptops = []
    for a in AGENTS:
        mine = [r for r in runs if r["agent"].startswith(a["name"].split()[0])
                or a["id"] in r["agent"].lower()]
        last = mine[0] if mine else None
        laptops.append({
            "agent": a["name"], "role": a["role"],
            "permissions": a["permissions"],
            "runs": len(mine),
            "last_run": (last["created_at"] + " — " + last["summary"][:80])
                          if last else "idle — no runs yet",
            "status": "active" if last else "idle",
        })
    # recent events (the observability feed)
    with hubdb.conn() as c:
        evs = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 20")\
            .fetchall()
    return {"ok": True, "laptops": laptops,
            "events": [dict(e) for e in evs]}


def calendar() -> dict:
    """List scheduled posts (the drag-drop UI just moves these)."""
    return {"ok": True, "scheduled": hubdb.list_scheduled()}


def reschedule(payload: dict) -> dict:
    """Drag-drop = update scheduled_at on ONE row. That's it."""
    hubdb.reschedule_post(int(payload["post_id"]),
                            payload["scheduled_at"])
    hubdb.log_event("reschedule", f"post#{payload['post_id']} -> "
                      f"{payload['scheduled_at']}")
    return {"ok": True}


# ---------------- Canary (selector health, dry-run) ----------------
def canary() -> dict:
    """Dry-run selector health checks against public pages — NO login,
    NO posting. Selector failures logged to the events table.
    Also reads agent-reach (MCP) platform availability."""
    from playwright.sync_api import sync_playwright
    checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            pg = browser.new_context(
                viewport={"width": 1280, "height": 900}).new_page()
            # IG login form (2026: name=email + name=pass)
            try:
                pg.goto("https://www.instagram.com/accounts/login/",
                          wait_until="domcontentloaded", timeout=30_000)
                pg.wait_for_selector(
                    "input[name='email'], input[name='username']",
                    timeout=15_000)
                ok = bool(pg.query_selector("input[name='pass']"))
                checks.append({"flow": "instagram_login",
                                 "status": "ok" if ok else
                                 "SELECTOR CHANGED (pass field missing)"})
            except Exception as e:
                checks.append({"flow": "instagram_login",
                                 "status": f"FAIL: {str(e)[:80]}"})
            # YT upload page reachable
            try:
                pg.goto("https://www.youtube.com/upload",
                          wait_until="domcontentloaded", timeout=30_000)
                checks.append({"flow": "youtube_upload",
                                 "status": "reachable"})
            except Exception as e:
                checks.append({"flow": "youtube_upload",
                                 "status": f"FAIL: {str(e)[:80]}"})
        finally:
            browser.close()
    # agent-reach MCP availability (which platforms it can research)
    try:
        import subprocess, sys as _sys
        proc = subprocess.run(["agent-reach", "doctor", "--json"],
                                capture_output=True, text=True, timeout=120)
        doc = json.loads(proc.stdout or "{}")
        mcp_platforms = {k: v.get("status") for k, v in doc.items()
                           if isinstance(v, dict) and v.get("status")}
        checks.append({"flow": "agent_reach_mcp",
                         "status": "ok",
                         "platforms": mcp_platforms})
    except Exception as e:
        checks.append({"flow": "agent_reach_mcp",
                         "status": f"unavailable: {str(e)[:60]}"})
    bad = [c for c in checks if c["status"] != "ok"
             and c["status"] != "reachable"]
    for b in bad:
        hubdb.log_event("canary_fail", f"{b['flow']}: {b['status']}")
    hubdb.log_event("canary_run", f"{len(checks)} checks, "
                      f"{len(bad)} failures")
    return {"ok": True, "checks": checks,
            "note": "dry-run, no logins. Failures are in the event "
                    "table — the fleet view reads them."}


# ---------------- Competitor cron (through the job queue) ----------------
def competitor_snapshot(handle: str, platform: str = "instagram") -> dict:
    """Scrape a competitor's PUBLIC profile (no login) and store a
    time-series snapshot — growth curves come free."""
    from playwright.sync_api import sync_playwright
    user = handle.lstrip("@")
    url = {"instagram": f"https://www.instagram.com/{user}/",
             "tiktok": f"https://www.tiktok.com/@{user}",
             "threads": f"https://www.threads.net/@{user}"}.get(
        platform, f"https://www.instagram.com/{user}/")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            pg = browser.new_context(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36")).new_page()
            pg.goto(url, wait_until="domcontentloaded", timeout=45_000)
            pg.wait_for_timeout(4_000)
            html = pg.content()
            m = re.search(r'property="og:description" content="([^"]*)"',
                          html)
            desc = m.group(1) if m else ""
            fm = re.search(r"([\d.,]+)\s*Followers", desc, re.I)
            fp = re.search(r"([\d.,]+)\s*Posts", desc, re.I)
            followers = (re.sub(r"[^\d.]", "", fm.group(1)) if fm else "0")
            posts_n = (re.sub(r"[^\d.]", "", fp.group(1)) if fp else "0")
            followers = int(float(followers)) if followers else 0
            posts_n = int(float(posts_n)) if posts_n else 0
            # time-series snapshot (never overwrites)
            hubdb.save_metric(platform, handle, followers=followers,
                                posts=posts_n)
            with hubdb.conn() as c:
                c.execute("INSERT INTO competitors(handle,platform,url,"
                            "followers,posts,last_seen) VALUES(?,?,?,?,?,?)",
                            (handle, platform, url, followers, posts_n,
                             time.strftime("%Y-%m-%d %H:%M")))
            # growth vs previous snapshot
            with hubdb.conn() as c:
                prev = c.execute(
                    "SELECT followers FROM metrics WHERE platform=? AND "
                    "account_id=? AND captured_at < datetime('now',"
                    "'-1 hour') ORDER BY id DESC LIMIT 1",
                    (platform, handle)).fetchone()
            growth = (followers - prev["followers"]) if prev else None
            return {"ok": True, "handle": handle, "platform": platform,
                    "followers": followers, "posts": posts_n,
                    "growth_since_last": growth}
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}
        finally:
            browser.close()


def competitor_cron(handles: list[str], platform: str = "instagram") -> dict:
    """Enqueue competitor snapshots through the SAME job queue as
    everything else (per-platform rate limit: max 5 per run)."""
    import job_runner
    enq = []
    for h in handles[:5]:   # ponytail: per-run cap = rate limit
        job_id = job_runner.enqueue("competitor-snapshot",
                                      {"handle": h, "platform": platform})
        enq.append({"handle": h, "job_id": job_id})
    hubdb.log_event("competitor_cron", f"{len(enq)} queued ({platform})")
    return {"ok": True, "queued": enq,
            "note": "worker runs them; poll /api/jobs"}
