"""Browser fallback poster for Instagram accounts with NO API access.

Drives a VISIBLE (headed) Chromium via Playwright so a human can
handle Instagram's login, 2FA, and any checkpoint challenges.
Use this only for accounts that have no Graph API token.

WARNING: Instagram aggressively fights automation. Automated logins
can trigger checkpoints or bans. The Graph API path (instagram_graph.py)
is the reliable way; this is a last-resort fallback. Never store
plaintext passwords in git — social_accounts.json is local only.

Run:
  .venv\\Scripts\\python.exe browser_poster.py ^
      --username uchihashishui881 --password '...' ^
      --video C:\\path\\clip.mp4 --caption "..." --type reel
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import ai_engine as ai  # noqa: E402


def _wait_for_text(page, text: str, timeout: int = 60_000):
    """Click a button/menu item by visible text; tolerate changes."""
    for sel in (f"text={text}", f":text('{text}')",
                f"button:has-text('{text}')",
                f"div[role='button']:has-text('{text}')"):
        try:
            el = page.wait_for_selector(sel, timeout=timeout // 4,
                                          state="visible")
            if el:
                el.click()
                return True
        except Exception:
            continue
    return False


def login(page, username: str, password: str) -> bool:
    """Open Instagram and log in. With a persistent profile
    (persistent_context), cookies survive — after ONE manual login
    per account this whole flow is skipped."""
    page.goto("https://www.instagram.com/",
                wait_until="domcontentloaded", timeout=60_000)
    time.sleep(3)
    # already logged in? (persistent profile with valid cookies)
    if page.query_selector("svg[aria-label*='Profile']") or \
            page.query_selector("a[href*='/direct/inbox/']"):
        print(">> already logged in (saved session) — skipping login")
        return True
    page.goto("https://www.instagram.com/accounts/login/",
                wait_until="domcontentloaded", timeout=60_000)
    try:
        # 2026 login form: username=name/email, password=name/pass
        el = page.wait_for_selector(
            "input[name='email'], input[name='username']",
            timeout=30_000)
        el.fill(username)
        pw = page.fill("input[name='pass']", password, timeout=20_000)
        # the real submit input is hidden; the visible Log in is a
        # role-button — Enter in the password field is the reliable way
        page.keyboard.press("Enter")
    except Exception as e:
        print("login fill failed:", e)
        return False
    print(">> If Instagram asks for 2FA / a checkpoint, complete it "
          "in the browser window now (up to 5 min)...")
    # wait until we're actually logged in (profile avatar appears);
    # if a checkpoint appears, TELL the user clearly and wait
    for _ in range(300):
        try:
            url = page.url
            if "challenge" in url or "checkpoint" in url:
                if _ % 30 == 0:
                    print(">> CHECKPOINT DETECTED — complete it in the "
                          "browser window (code/SMS/email), I'll wait...")
            elif page.query_selector(
                    "svg[aria-label*='Profile']") or \
                    page.query_selector("a[href*='/direct/inbox/']"):
                return True
        except Exception:
            pass
        time.sleep(1)
    print(">> Timed out waiting for login. Check the browser window.")
    return False


def _pick_file(page, path: str) -> bool:
    """Instagram's create dialog has a hidden file input."""
    for sel in ("input[type='file']",
                "input[accept*='video']",
                "input[accept*='image']"):
        try:
            el = page.query_selector(sel)
            if el:
                el.set_input_files(path)
                return True
        except Exception:
            continue
    return False


def post_media(page, media_path: str, caption: str,
                 media_type: str = "reel") -> bool:
    """Post a video/photo. media_type: reel | video | photo | story."""
    # natural feed browse first — real session, not a straight hit
    try:
        page.goto("https://www.instagram.com/",
                    wait_until="domcontentloaded", timeout=60_000)
        time.sleep(3)
        page.mouse.wheel(0, 600)
        time.sleep(2)
    except Exception:
        pass
    # Go to the create page (more reliable than clicking the + button)
    url = "https://www.instagram.com/create/reel/" \
        if media_type == "reel" else \
        "https://www.instagram.com/create/"
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(3)

    if not _pick_file(page, media_path):
        # fallback: click the big "Select from computer" area
        _wait_for_text(page, "Select from computer") or \
            _wait_for_text(page, "Select files")
        time.sleep(1)
        if not _pick_file(page, media_path):
            print(">> Could not find the file input. "
                  "Select the file manually in the browser.")
            input(">> Press Enter here after you've picked the file...")

    # wait for upload to finish
    print(">> Uploading (large files take a while)...")
    for _ in range(120):
        try:
            nxt = page.query_selector("button:has-text('Next')")
            if nxt and nxt.is_enabled():
                break
        except Exception:
            pass
        time.sleep(2)

    if media_type == "story":
        # stories share immediately after upload
        _wait_for_text(page, "Share") or _wait_for_text(page, "Your story")
        print(">> Story posted (or complete it in the browser).")
        return True

    # reels may show an editor — skip to Next if present
    _wait_for_text(page, "Next")
    time.sleep(2)
    # caption box
    try:
        cap = page.wait_for_selector(
            "textarea[aria-label*='caption'], textarea[aria-label*='Caption']",
            timeout=15_000)
        if cap:
            cap.fill(caption)
    except Exception:
        print(">> Caption box not found — add it manually.")
    # share
    if _wait_for_text(page, "Share"):
        print(">> Post published via browser.")
        return True
    print(">> 'Share' not found — finish posting in the browser.")
    return False


def yt_post_media(page, media_path: str, title: str, desc: str) -> bool:
    """Upload a video via YouTube Studio (visible browser)."""
    # natural browse first — real session
    try:
        page.goto("https://www.youtube.com/",
                    wait_until="domcontentloaded", timeout=60_000)
        time.sleep(3)
        page.mouse.wheel(0, 600)
        time.sleep(2)
    except Exception:
        pass
    page.goto("https://www.youtube.com/upload",
                wait_until="domcontentloaded", timeout=60_000)
    time.sleep(3)
    if not _pick_file(page, media_path):
        _wait_for_text(page, "Select files") or _wait_for_text(page, "Select")
        time.sleep(1)
        if not _pick_file(page, media_path):
            print(">> Could not find the file input — select it manually.")
            input(">> Press Enter after you've picked the file...")
    print(">> Uploading (large files take a while)...")
    # details page: title/description are contenteditable #textboxes
    boxes = None
    for _ in range(90):
        try:
            if page.locator("#textbox").count() >= 1:
                boxes = page.locator("#textbox")
                break
        except Exception:
            pass
        time.sleep(2)
    try:
        if boxes:
            boxes.nth(0).click()
            page.keyboard.press("Control+a")
            page.keyboard.type(title, delay=20)
            if desc:
                time.sleep(1)
                boxes.nth(1).click()
                page.keyboard.type(desc, delay=8)
    except Exception as e:
        print(">> Title/description fill failed:", e,
              "— set them manually.")
    # Next (checks) → Next (visibility) → Publish
    _wait_for_text(page, "Next")
    time.sleep(2)
    _wait_for_text(page, "Next")
    time.sleep(2)
    try:
        page.click("tp-yt-paper-radio-button[name='PUBLIC']",
                     timeout=10_000)
    except Exception:
        _wait_for_text(page, "Public")
    if _wait_for_text(page, "Publish"):
        print(">> YouTube video published via browser.")
        return True
    print(">> 'Publish' not found — finish in the browser.")
    return False


def fb_login(page, email: str, password: str) -> bool:
    """Log into Facebook. Human handles 2FA."""
    page.goto("https://www.facebook.com/login",
                wait_until="domcontentloaded", timeout=60_000)
    try:
        page.fill("input[name='email']", email, timeout=20_000)
        page.fill("input[name='pass']", password, timeout=20_000)
        page.click("button[name='login']", timeout=20_000)
    except Exception as e:
        print("Facebook login fill failed:", e)
        return False
    print(">> If Facebook asks for 2FA, complete it in the browser now "
          "(up to 3 min)...")
    for _ in range(180):
        try:
            if "login" not in page.url:
                return True
        except Exception:
            pass
        time.sleep(1)
    print(">> Timed out waiting for Facebook login.")
    return False


def fb_post_media(page, media_path: str, message: str) -> bool:
    """Post a video to Facebook (timeline) via browser."""
    # natural browse first
    try:
        page.goto("https://www.facebook.com/",
                    wait_until="domcontentloaded", timeout=60_000)
        time.sleep(3)
        page.mouse.wheel(0, 600)
        time.sleep(2)
    except Exception:
        pass
    _wait_for_text(page, "Photo/video") or _wait_for_text(
        page, "Photo/Video") or _wait_for_text(page, "Video")
    time.sleep(2)
    if not _pick_file(page, media_path):
        print(">> Could not find the file input — select it manually.")
        input(">> Press Enter after you've picked the file...")
    print(">> Uploading...")
    try:
        box = page.wait_for_selector(
            "div[role='textbox'][contenteditable='true']", timeout=30_000)
        if box:
            box.click()
            page.keyboard.type(message, delay=10)
    except Exception:
        print(">> Message box not found — type it manually.")
    if _wait_for_text(page, "Post"):
        print(">> Facebook video posted via browser.")
        return True
    print(">> 'Post' not found — finish in the browser.")
    return False


def run(username: str, password: str, video: str, caption: str,
        media_type: str, platform: str = "instagram",
        title: str = "") -> None:
    from browser_profile import open_profile
    pw, browser, page = open_profile(username)
    try:
        if platform == "youtube":
            from browser_commenter import google_login
            if not google_login(page, username, password):
                print("Login failed — aborting.")
                return
            ok = yt_post_media(page, video, title or caption, caption)
        elif platform == "facebook":
            if not fb_login(page, username, password):
                print("Login failed — aborting.")
                return
            ok = fb_post_media(page, video, caption)
        else:
            if not login(page, username, password):
                print("Login failed — aborting.")
                return
            ok = post_media(page, video, caption, media_type)
        print("RESULT:", "posted" if ok else "needs manual finish")
    finally:
        input(">> Press Enter to close the browser...")
        browser.close()
        pw.stop()


def run_post_multi(jobs: dict) -> None:
    """Sequential accounts: each logs in and posts with its OWN
    unique title/caption (never identical across accounts).

    Uses PERSISTENT profiles: after one manual login per account,
    every future run skips login entirely."""
    platform = jobs.get("platform", "instagram")
    items = jobs.get("jobs", [])
    results = []
    from browser_profile import open_profile
    pw = None
    for i, job in enumerate(items, 1):
        user = job.get("username", "")
        print(f"\n=== Post {i}/{len(items)}: {user} ===")
        pw, browser, page = open_profile(user)
        try:
            if platform == "youtube":
                from browser_commenter import google_login
                if not google_login(page, user, job.get("password", "")):
                    results.append({"username": user, "ok": False,
                                      "error": "login failed"})
                    continue
                ok = yt_post_media(page, job.get("file"),
                                     job.get("title", ""),
                                     job.get("caption", ""))
            elif platform == "facebook":
                if not fb_login(page, user, job.get("password", "")):
                    results.append({"username": user, "ok": False,
                                      "error": "login failed"})
                    continue
                ok = fb_post_media(page, job.get("file"),
                                     job.get("caption", ""))
            else:
                if not login(page, user, job.get("password", "")):
                    results.append({"username": user, "ok": False,
                                      "error": "login failed — complete "
                                               "the login once in the "
                                               "browser; the session "
                                               "then persists"})
                    continue
                ok = post_media(page, job.get("file"),
                                  job.get("caption", ""),
                                  job.get("media_type", "reel"))
            results.append({"username": user, "ok": ok,
                              "title": (job.get("title") or "")[:60]})
        except Exception as e:
            results.append({"username": user, "ok": False,
                              "error": str(e)[:150]})
        finally:
            browser.close()
            pw.stop()
    print("\nRESULTS:", json.dumps(results, indent=2))


def setup_login(username: str) -> None:
    """ONE-TIME manual login: opens the account's persistent profile,
    you log in manually (checkpoint/2FA included), press Enter here.
    The session then persists for all future runs."""
    from browser_profile import open_profile
    pw, browser, page = open_profile(username)
    try:
        page.goto("https://www.instagram.com/accounts/login/",
                    wait_until="domcontentloaded", timeout=60_000)
        if page.query_selector("svg[aria-label*='Profile']"):
            print(f">> {username}: already logged in ✓")
            return
        print(f">> {username}: log in MANUALLY in the browser window "
              f"(complete any checkpoint/2FA).")
        input(">> Press Enter here AFTER you're logged in...")
        ok = bool(page.query_selector("svg[aria-label*='Profile']")) or \
            "accounts/login" not in page.url
        print(">>", username, ":", "session SAVED ✓" if ok else
              "login not detected — try again")
    finally:
        browser.close()
        pw.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="instagram",
                    choices=["instagram", "youtube", "facebook"])
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--video", default="")
    ap.add_argument("--caption", default="")
    ap.add_argument("--type", default="reel",
                    choices=["reel", "video", "photo", "story"])
    ap.add_argument("--title", default="")   # raw title for auto-SEO
    ap.add_argument("--jobs-file",
                    help="JSON file with multi-account posting jobs")
    ap.add_argument("--setup-login", action="store_true",
                    help="one-time manual login for --username")
    args = ap.parse_args()

    if args.setup_login and args.username:
        setup_login(args.username)
        return

    if args.jobs_file:
        jobs = json.loads(Path(args.jobs_file).read_text(encoding="utf-8"))
        run_post_multi(jobs)
        return
    if not (args.username and args.password and args.video):
        ap.error("single-post mode needs --username/--password/--video "
                 "(or pass --jobs-file for multi-account)")

    caption = args.caption
    if not caption and (args.title or args.video):
        # auto-generate content-aware SEO caption from the raw idea
        seo = ai.generate_seo(args.title or args.video,
                              platform=args.platform)
        caption = seo["description"]
        print("Auto SEO caption:\n", caption, "\n")
    run(args.username, args.password, args.video, caption, args.type,
        args.platform, args.title)


if __name__ == "__main__":
    main()
