"""Browser commenter — comment on / watch Instagram AND YouTube
posts from accounts via visible browsers (human-supervised).

Every action browses the platform feed NATURALLY first (real session
activity — looks like a person, not a bot hitting a link).

Modes:
  single: log in as ONE account, comment one text on a URL.
  multi (--jobs-file): loop accounts one at a time — each account
      gets its OWN unique comment (never the same text twice), or
      just watches the linked video (watch mode, research).

Run single:
  .venv\\Scripts\\python.exe browser_commenter.py --platform instagram ^
      --username X --password Y --url https://www.instagram.com/reel/ABC/ ^
      --comment "Great content!"
Run multi:
  .venv\\Scripts\\python.exe browser_commenter.py --jobs-file jobs.json
  jobs.json: {"platform": "instagram"|"youtube", "url": "...",
              "watch": false,
              "jobs": [{"username": "...", "password": "...",
                        "comment": "..."}, ...]}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import browser_poster as bp  # noqa: E402  (reuse IG login)


def browse_naturally(page, platform: str) -> None:
    """Browse the feed briefly BEFORE the target action — a real
    session, not a straight hit on the target link."""
    try:
        if platform == "youtube":
            page.goto("https://www.youtube.com/",
                        wait_until="domcontentloaded", timeout=60_000)
            time.sleep(4)
            for _ in range(3):
                page.mouse.wheel(0, 600)
                time.sleep(3)
        elif platform == "facebook":
            page.goto("https://www.facebook.com/",
                        wait_until="domcontentloaded", timeout=60_000)
            time.sleep(4)
            for _ in range(3):
                page.mouse.wheel(0, 700)
                time.sleep(3)
        else:
            page.goto("https://www.instagram.com/reels/",
                        wait_until="domcontentloaded", timeout=60_000)
            time.sleep(4)
            for _ in range(3):
                page.keyboard.press("ArrowDown")
                time.sleep(3)
    except Exception:
        pass


def google_login(page, email: str, password: str) -> bool:
    """Sign into Google/YouTube. Human handles 2FA."""
    page.goto("https://accounts.google.com/ServiceLogin",
                wait_until="domcontentloaded", timeout=60_000)
    try:
        page.fill("input[type='email']", email, timeout=20_000)
        page.click("#identifierNext, button:has-text('Next')",
                     timeout=20_000)
        time.sleep(4)
        page.fill("input[type='password']", password, timeout=20_000)
        page.click("#passwordNext, button:has-text('Next')",
                     timeout=20_000)
    except Exception as e:
        print("Google login fill failed:", e)
        return False
    print(">> If Google asks for 2FA, complete it in the browser now "
          "(up to 3 min)...")
    for _ in range(180):
        try:
            if "accounts.google.com" not in page.url:
                return True
        except Exception:
            pass
        time.sleep(1)
    print(">> Timed out waiting for Google login.")
    return False


def login_for(page, platform: str, username: str, password: str) -> bool:
    if platform == "youtube":
        return google_login(page, username, password)
    if platform == "facebook":
        return bp.fb_login(page, username, password)
    return bp.login(page, username, password)


def _fb_comment(page, text: str) -> bool:
    """Facebook comment box is a contenteditable under the post;
    Enter submits it."""
    time.sleep(2)
    try:
        boxes = page.locator("div[role='textbox'][contenteditable='true']")
        if boxes.count() > 0:
            box = boxes.first
            box.click()
            page.keyboard.type(text, delay=20)
            time.sleep(1)
            page.keyboard.press("Enter")
            print(">> Facebook comment posted.")
            return True
    except Exception as e:
        print(">> FB comment box not found:", e)
    input(f">> Type it manually: {text} — then press Enter...")
    return True


def comment(page, url: str, text: str, platform: str = "instagram") -> bool:
    """Open a post/reel/video and leave a comment."""
    browse_naturally(page, platform)
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(4 if platform == "instagram" else 6)

    if platform == "youtube":
        return _yt_comment(page, text)
    if platform == "facebook":
        return _fb_comment(page, text)

    for sel in ("textarea[aria-label*='comment']",
                "textarea[aria-label*='Comment']",
                "input[aria-label*='comment']",
                "input[aria-label*='Comment']",
                "text=Add a comment..."):
        try:
            el = page.wait_for_selector(sel, timeout=10_000,
                                              state="visible")
            if el:
                el.click()
                break
        except Exception:
            continue

    try:
        box = page.wait_for_selector(
            "textarea[aria-label*='comment'], "
            "textarea[aria-label*='Comment'], "
            "input[aria-label*='comment'], "
            "input[aria-label*='Comment']",
            timeout=10_000)
        if box:
            box.fill(text)
        else:
            print(f">> Comment box not found — type it manually: {text}")
            input(">> Press Enter after commenting...")
            return True
    except Exception as e:
        print(">> Could not find comment box:", e)
        input(f">> Type it manually: {text} — then press Enter...")
        return True

    for sel in ("button:has-text('Post')",
                "div[role='button']:has-text('Post')",
                "text=Post"):
        try:
            btn = page.wait_for_selector(sel, timeout=8_000,
                                               state="visible")
            if btn and btn.is_enabled():
                btn.click()
                print(">> Comment posted.")
                return True
        except Exception:
            continue
    print(">> 'Post' button not found — submit manually.")
    return False


def _yt_comment(page, text: str) -> bool:
    """YouTube comment box is a contenteditable below the video."""
    page.mouse.wheel(0, 1400)   # scroll to comments
    time.sleep(3)
    for sel in ("#placeholder-area",
                "ytd-comment-simplebox-renderer #placeholder-area"):
        try:
            el = page.wait_for_selector(sel, timeout=10_000,
                                              state="visible")
            if el:
                el.click()
                break
        except Exception:
            continue
    time.sleep(2)
    try:
        box = page.wait_for_selector(
            "#contenteditable-root", timeout=10_000)
        if box:
            box.click()
            page.keyboard.type(text, delay=30)
        else:
            print(f">> Comment box not found — type it manually: {text}")
            input(">> Press Enter after commenting...")
            return True
    except Exception as e:
        print(">> Could not find YouTube comment box:", e)
        input(f">> Type it manually: {text} — then press Enter...")
        return True
    time.sleep(1)
    for sel in ("#submit-button",
                "ytd-comment-dialog-renderer #submit-button",
                "button:has-text('Comment')"):
        try:
            btn = page.wait_for_selector(sel, timeout=8_000,
                                               state="visible")
            if btn and btn.is_enabled():
                btn.click()
                print(">> YouTube comment posted.")
                return True
        except Exception:
            continue
    print(">> 'Comment' button not found — submit manually.")
    return False


def run(username: str, password: str, url: str, text: str,
        platform: str = "instagram") -> None:
    from browser_profile import open_profile
    pw, browser, page = open_profile(username)
    try:
        if not login_for(page, platform, username, password):
            print("Login failed — aborting.")
            return
        ok = comment(page, url, text, platform)
        print("RESULT:", "commented" if ok else "needs manual finish")
    finally:
        input(">> Press Enter to close the browser...")
        browser.close()
        pw.stop()


def run_multi(jobs: dict) -> None:
    """Sequential accounts, ONE browser at a time — persistent
    profiles (one manual login per account, then it persists).

    watch=True  → each account watches the linked video.
    watch=False → each account comments its OWN unique text."""
    url = jobs.get("url", "")
    watch = bool(jobs.get("watch"))
    platform = jobs.get("platform", "instagram")
    items = jobs.get("jobs", [])
    results = []
    from browser_profile import open_profile
    for i, job in enumerate(items, 1):
        user = job.get("username", "")
        ctext = job.get("comment", "")
        print(f"\n=== Account {i}/{len(items)}: {user} "
              f"({'watch' if watch else 'comment'} on {platform}) ===")
        pw, browser, page = open_profile(user)
        try:
            if not login_for(page, platform, user,
                               job.get("password", "")):
                results.append({"username": user, "ok": False,
                                  "error": "login failed — log in once "
                                           "in the browser, session "
                                           "persists"})
                continue
            if watch:
                browse_naturally(page, platform)
                page.goto(url, wait_until="domcontentloaded",
                            timeout=60_000)
                print(">> Target video open and playing. Watch it, "
                      "press Enter here when done.")
                input()
                results.append({"username": user, "ok": True,
                                  "watched": True})
            else:
                ok = comment(page, url, ctext, platform)
                results.append({"username": user, "ok": ok,
                                  "comment": ctext})
        except Exception as e:
            results.append({"username": user, "ok": False,
                              "error": str(e)[:150]})
        finally:
            browser.close()
            pw.stop()
    print("\nRESULTS:", json.dumps(results, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="instagram",
                    choices=["instagram", "youtube", "facebook"])
    ap.add_argument("--username")
    ap.add_argument("--password")
    ap.add_argument("--url")
    ap.add_argument("--comment")
    ap.add_argument("--jobs-file")
    args = ap.parse_args()

    if args.jobs_file:
        jobs = json.loads(Path(args.jobs_file).read_text(encoding="utf-8"))
        run_multi(jobs)
        return
    if not (args.username and args.password and args.url):
        ap.error("need --username/--password/--url, or --jobs-file")
    run(args.username, args.password, args.url, args.comment or "",
        args.platform)


if __name__ == "__main__":
    main()
