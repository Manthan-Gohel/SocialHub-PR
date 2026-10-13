"""Unified inbox + reply agent.

- fetch_browser(acct): reads DMs/comments/mentions via the VISIBLE
  browser (frontend path) when no Graph token — scrapes the
  notifications page, stores everything in the inbox table.
- generate_reply(item, account): the Reply agent — writes a reply in
  the account's voice guide (LLM strong tier), Reviewer gates it.
- reply_browser(acct, url, text): posts the reply via visible browser,
  human-supervised.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import hubdb

BASE = Path(__file__).resolve().parent
sys_path = str(BASE)


# ---------------- Frontend fetch (browser, no token needed) ----------------
def fetch_browser(acct: dict, platform: str = "instagram") -> dict:
    """Scrape the account's notifications page (comments/mentions/
    follows) via visible browser — the frontend path when no token."""
    from playwright.sync_api import sync_playwright
    if not acct.get("username") or not acct.get("password"):
        return {"ok": False, "error": "account needs username+password "
                                       "for the browser inbox"}
    user, pw = acct["username"], acct["password"]
    found = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_context(
            viewport={"width": 1280, "height": 900}).new_page()
        try:
            import browser_poster as bp
            if not bp.login(page, user, pw):
                return {"ok": False, "error": "login failed — aborting"}

            if platform == "instagram":
                page.goto("https://www.instagram.com/accounts/activity/",
                            wait_until="domcontentloaded", timeout=60_000)
                time.sleep(5)
                # notification rows: comments/mentions/follows
                rows = page.eval_on_selector_all(
                    "div[role='tablist'] ~ div a, div._a9_1",
                    """els => els.slice(0, 40).map(e => e.innerText)""")
                for txt in rows:
                    if not txt:
                        continue
                    first_line = txt.split("\n")[0]
                    kind = "comment"
                    if "started following" in txt.lower() or \
                            "followed you" in txt.lower():
                        kind = "follow"
                    elif "mentioned" in txt.lower():
                        kind = "mention"
                    hubdb.save_inbox(platform, acct.get("_id"),
                                       acct.get("name"), kind,
                                       first_line[:40], txt[:300], "")
                    found += 1
            elif platform == "facebook":
                page.goto("https://www.facebook.com/notifications",
                            wait_until="domcontentloaded", timeout=60_000)
                time.sleep(5)
                rows = page.eval_on_selector_all(
                    "div[aria-label='Notifications'] div[role='link']",
                    """els => els.slice(0, 40).map(e => e.innerText)""")
                for txt in rows:
                    if not txt:
                        continue
                    hubdb.save_inbox(platform, acct.get("_id"),
                                       acct.get("name"), "comment",
                                       "facebook", txt[:300], "")
                    found += 1
            else:
                return {"ok": False, "error": f"browser inbox not built "
                          f"for {platform} — open its notifications "
                          f"manually and paste"}
        finally:
            input(">> Press Enter to close the browser...")
            browser.close()
    hubdb.log_event("inbox_fetch", f"{platform}/{acct.get('name')}: "
                      f"{found} items")
    return {"ok": True, "platform": platform, "account": acct.get("name"),
            "items_found": found}


# ---------------- Reply agent ----------------
def generate_reply(item: dict, account: dict) -> dict:
    """Write a reply in the account's voice. Reviewer gates it."""
    import llm
    import trust
    text = item.get("text", "")
    from_user = item.get("from_user", "user")
    kind = item.get("kind", "comment")

    voice = account.get("voice") or {}
    pillars = account.get("pillars") or []
    voice_note = (f"Brand voice: {json.dumps(voice, ensure_ascii=False)}. "
                  f"Content pillars: {', '.join(pillars)}."
                  if (voice or pillars) else
                  "Keep it warm, short, human, on-brand.")

    prompt = (f"You are replying to a {kind} on {item.get('platform')} "
              f"from {from_user}. Their message: \"{text[:300]}\"\n"
              f"{voice_note}\n"
              f"Write ONE natural reply (1-2 sentences, friendly, "
              f"specific to their message). Return only the reply text.")
    out = llm.chat(prompt, max_tokens=300, tier="strong")

    reply = (out or "").strip()
    if not reply:
        # template fallback
        templates = ["Thanks {u}! 🙏 Means a lot.",
                       "Appreciate you {u}! More coming 👀",
                       "Thank you! Glad you liked it ❤️"]
        reply = templates[len(text) % len(templates)].format(u=from_user)

    # Reviewer gate
    review = trust.reviewer_check({"kind": "comment", "text": reply,
                                     "account": account})
    return {"ok": True, "reply": reply,
              "reviewer": review["verdict"],
              "issues": review["issues"]}


def reply_browser(acct: dict, url: str, text: str) -> dict:
    """Post the reply via the visible browser (human-supervised)."""
    from playwright.sync_api import sync_playwright
    if not acct.get("username") or not acct.get("password"):
        return {"ok": False, "error": "account needs username+password"}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_context(
            viewport={"width": 1280, "height": 900}).new_page()
        try:
            import browser_commenter as bc
            if not bc.login_for(page, "instagram",
                                  acct["username"],
                                  acct["password"]):
                return {"ok": False, "error": "login failed"}
            bc.comment(page, url, text, "instagram")
        finally:
            input(">> Press Enter to close the browser...")
            browser.close()
    hubdb.log_event("inbox_reply", f"replied: {text[:60]}")
    return {"ok": True}
