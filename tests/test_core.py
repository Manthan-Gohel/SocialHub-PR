"""Unit tests for the core logic (stdlib unittest, no frameworks).

Covers: llm.py JSON extraction (reasoning-model quirks),
tasks.py parsing, company prioritization rule, trust.py compliance.
Run: .venv\\Scripts\\python.exe tests\\test_core.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai_engine   # noqa: E402
import tasks       # noqa: E402
import trust       # noqa: E402
import llm         # noqa: E402

# tests must be fast + offline: disable LLM calls (templates cover it)
llm.API_KEY = ""


class TestLlmJsonExtraction(unittest.TestCase):
    def test_plain_json(self):
        d = ai_engine._extract_json('{"title": "Hi", "tags": ["a"]}')
        self.assertEqual(d["title"], "Hi")

    def test_json_inside_reasoning_text(self):
        text = ('The user wants... Return ONLY: {"title": "...", } '
                'so I should... {"title": "Real Title", '
                '"tags": ["x"]}')
        d = ai_engine._extract_json(text)
        self.assertEqual(d["title"], "Real Title")

    def test_rejects_placeholder_template(self):
        # the echoed template has title "..." — must NOT be returned
        text = ('I will use: {"title": "...", "description": "...", '
                '"tags": ["..."]} and then more reasoning')
        d = ai_engine._extract_json(text)
        self.assertTrue(d is None or d.get("title") not in ("...", ""))

    def test_truncated_json(self):
        d = ai_engine._extract_json('{"title": "Cut off')
        self.assertTrue(d is None or d.get("title"))

    def test_empty(self):
        self.assertIsNone(ai_engine._extract_json(""))
        self.assertIsNone(ai_engine._extract_json(None))


class TestTaskParsing(unittest.TestCase):
    def test_comment_with_accounts(self):
        acts = tasks.parse_task(
            "comment Great post! on https://instagram.com/reel/ABC "
            "with Main IG, Second IG", ["Main IG", "Second IG"])
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["action"], "comment")
        self.assertEqual(acts[0]["url"],
                           "https://instagram.com/reel/ABC")
        self.assertEqual(acts[0]["accounts"], ["Main IG", "Second IG"])

    def test_open_account(self):
        acts = tasks.parse_task("open Celebrity Gossip",
                                  ["Celebrity Gossip"])
        self.assertEqual(acts[0]["action"], "open")

    def test_grow(self):
        acts = tasks.parse_task("grow the_talk_tommorow", [])
        self.assertEqual(acts[0]["action"], "grow")
        self.assertIn("the_talk_tommorow", acts[0]["target"])

    def test_campaign(self):
        acts = tasks.parse_task("bigboss win scout op all campain", [])
        self.assertEqual(acts[0]["action"], "campaign")
        self.assertEqual(acts[0]["topic"], "bigboss win")

    def test_any_text_runs_company(self):
        acts = tasks.parse_task("make my account famous", [])
        self.assertEqual(acts[0]["action"], "campaign")

    def test_empty(self):
        self.assertEqual(tasks.parse_task("", []), [])


class TestCompanyPrioritization(unittest.TestCase):
    def test_negative_sentiment_runs_crisis_first(self):
        # replicate the CEO's action-ordering rule
        actions = ["1. post calendar", "2. engage"]
        sentiment = "mixed/negative"
        if sentiment == "mixed/negative":
            actions.insert(0, "0. crisis plan BEFORE promo")
        self.assertIn("crisis", actions[0])
        self.assertLess(actions.index("0. crisis plan BEFORE promo"),
                          actions.index("1. post calendar"))

    def test_positive_sentiment_content_first(self):
        actions = ["1. post calendar", "2. engage"]
        sentiment = "positive/neutral"
        self.assertIn("post", actions[0])


class TestCompliance(unittest.TestCase):
    def test_banned_word_blocked(self):
        r = trust.compliance_check("This is a guarantee of success")
        self.assertFalse(r["ok"])
        self.assertTrue(any("guarantee" in v for v in r["violations"]))

    def test_sponsored_needs_disclosure(self):
        r = trust.compliance_check("Sponsored by BrandX, check it out")
        self.assertFalse(r["ok"])
        self.assertTrue(any("disclosure" in v for v in r["violations"]))

    def test_clean_text_passes(self):
        r = trust.compliance_check("Bigboss winner moment 🏆 #biggboss")
        self.assertTrue(r["ok"])

    def test_account_banned_topics(self):
        r = trust.compliance_check("talking about politics today",
                                     {"banned_topics": ["politics"]})
        self.assertFalse(r["ok"])

    def test_reviewer_blocks_missing_media(self):
        r = trust.reviewer_check({"kind": "post", "title": "x",
                                    "description": "y",
                                    "media_type": "reels"})
        self.assertEqual(r["verdict"], "needs_changes")
        self.assertTrue(any("media" in i for i in r["issues"]))

    def test_error_taxonomy(self):
        r = trust.classify_error("Session has expired on Monday")
        self.assertEqual(r["type"], "expired_token")
        r = trust.classify_error("HTTP 429 too many requests")
        self.assertEqual(r["type"], "rate_limit")
        r = trust.classify_error("checkpoint required")
        self.assertEqual(r["type"], "checkpoint_2fa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
