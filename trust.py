"""Trust boundaries: compliance checks, reviewer agent, error taxonomy.

- compliance_check(text, account) — banned words + disclosure +
  music/copyright flags BEFORE anything posts
- reviewer_check(item) — the Reviewer agent: accuracy/brand-safety/
  disclosure gate before output reaches the queue
- classify_error(e) — expired token vs checkpoint/2FA vs rate limit
  vs selector changed vs other; routes each to a different fix
"""
from __future__ import annotations

import re

# Default banned words (accounts can extend via banned_topics)
DEFAULT_BANNED_WORDS = ["guarantee", "risk-free", "no risk", "100% free money",
                        "clickbait", "cure", "miracle cure", "get rich"]
# Disclosure triggers that REQUIRE a label before posting
DISCLOSURE_TRIGGERS = ["sponsored", "ad ", "#ad", "paid partnership",
                       "gifted", "affiliate"]
# Music/copyright flags
MUSIC_FLAGS = ["copyrighted music", "commercial track", "top 40",
               "radio edit"]


def compliance_check(text: str, account: dict | None = None) -> dict:
    """Check text before posting. Returns ok + violations + fixes."""
    violations = []
    fixes = []
    low = (text or "").lower()

    banned = list(DEFAULT_BANNED_WORDS)
    if account and account.get("banned_topics"):
        banned += account["banned_topics"]
    for w in banned:
        if w and w.lower() in low:
            violations.append(f"banned word/topic: '{w}'")
            fixes.append(f"remove or rephrase '{w}'")

    # disclosure: sponsored content MUST carry #ad / Paid partnership
    needs_disclosure = any(t in low for t in
                             ("sponsored by", "paid partnership",
                              "#sponsored", "gifted by"))
    has_disclosure = any(t in low for t in ("#ad", "paid partnership",
                                              "#sponsored"))
    if needs_disclosure and not has_disclosure:
        violations.append("sponsored content without disclosure label")
        fixes.append("add '#ad' or 'Paid partnership with ...'")

    for f in MUSIC_FLAGS:
        if f in low:
            violations.append(f"possible music/copyright flag: '{f}'")
            fixes.append("use licensed/original audio")

    return {"ok": not violations, "violations": violations,
            "fixes": fixes}


def reviewer_check(item: dict) -> dict:
    """Reviewer/Compliance agent — checks an output (post/comment)
    before it reaches the queue: compliance + basic quality."""
    text = item.get("text") or item.get("description") \
        or item.get("caption") or ""
    account = item.get("account") if isinstance(item.get("account"), dict) \
        else None
    comp = compliance_check(text, account)
    issues = list(comp["violations"])

    # quality gates
    if item.get("title") and len(item["title"]) > 100:
        issues.append("title over 100 chars (will be truncated)")
    if text and len(text) > 2200:
        issues.append("description over 2200 chars (will be truncated)")
    if item.get("kind") == "post" and not item.get("file") \
            and item.get("media_type") != "text":
        issues.append("no media file attached")

    verdict = "approved" if not issues else "needs_changes"
    return {"reviewer": "🛡️ Reviewer/Compliance", "verdict": verdict,
            "issues": issues, "fixes": comp["fixes"],
            "grounded": item.get("grounded", None)}


def classify_error(err: str) -> dict:
    """Error taxonomy: route each failure type to its fix."""
    e = (err or "").lower()
    if "session has expired" in e or "code\":190" in e or \
            "error_subcode\":463" in e:
        return {"type": "expired_token",
                  "fix": "Refresh the token (🔑 Refresh IG token, or "
                         "paste a fresh one via Edit). Browser fallback "
                         "still works meanwhile."}
    if "checkpoint" in e or "challenge" in e or "2fa" in e or \
            "two-factor" in e:
        return {"type": "checkpoint_2fa",
                  "fix": "Complete the 2FA/checkpoint in the visible "
                         "browser window, then retry."}
    if "rate limit" in e or "429" in e or "too many requests" in e:
        return {"type": "rate_limit",
                  "fix": "Back off — the job runner retries with "
                         "exponential delay; daily caps prevent this."}
    if "selector" in e or "timeout" in e and "locator" in e or \
            "not found" in e and "input" in e:
        return {"type": "selector_changed",
                  "fix": "The platform changed its DOM (like IG's 2026 "
                         "login form). Update the selector in "
                         "browser_poster/browser_commenter; the daily "
                         "canary run catches this."}
    if "login failed" in e or "password was incorrect" in e:
        return {"type": "bad_credentials",
                  "fix": "Check the username/password in the account "
                         "Edit form."}
    return {"type": "other", "fix": str(err)[:200]}
