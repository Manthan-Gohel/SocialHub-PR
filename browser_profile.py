"""Persistent browser profiles — one folder per account.

Instagram blocks repeated automated LOGINS from the same IP
(checkpoints, rate limits). The fix: log in ONCE manually per
account, cookies persist in the profile folder, every future run
skips login entirely.

Usage:
  from browser_profile import open_profile
  browser, page = open_profile("anyway_bleeed")
  ... do everything ...
  browser.close()

First run for an account: a browser opens, YOU log in once
(checkpoint/2FA included), then press Enter in the terminal.
After that the session is saved forever.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
PROFILES = BASE / "browser_profiles"


def open_profile(username: str):
    """Launch chromium with a persistent profile for this account.

    Returns (playwright_ctx_manager_entered, browser, page) — call
    browser.close() when done."""
    prof = PROFILES / re.sub(r"[^a-zA-Z0-9._-]", "_", username or "default")
    prof.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    browser = pw.chromium.launch_persistent_context(
        str(prof), headless=False,
        viewport={"width": 1280, "height": 900})
    page = browser.pages[0] if browser.pages else browser.new_page()
    return pw, browser, page
