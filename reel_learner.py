"""Reel learner — analyze a public Instagram reel to LEARN how it
performs: which hashtags it uses, view/like/comment counts, and
simple insights. Learned hashtags feed back into trending_tags.json
so future SEO gets smarter.

Research tool (public data), not engagement manipulation.

Run:
  .venv\\Scripts\\python.exe reel_learner.py --url https://www.instagram.com/reel/ABC/
Optional (if login wall): --username X --password Y
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _num(s: str | None) -> int | None:
    """'1,234' / '12.5K' / '3M' → int."""
    if not s:
        return None
    s = s.strip().replace(",", "")
    m = re.match(r"([\d.]+)\s*([KMB])", s, re.I)
    if m:
        v = float(m.group(1))
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[m.group(2).lower()]
        return int(v * mult)
    try:
        return int(float(s))
    except ValueError:
        return None


def _counts_from_text(text: str) -> dict:
    """Extract views/likes/comments from an Instagram description blob."""
    out = {}
    for key, pat in (("views", r"([\d.,]+\s*[KMB]?)\s*views"),
                     ("likes", r"([\d.,]+\s*[KMB]?)\s*likes"),
                     ("comments", r"([\d.,]+\s*[KMB]?)\s*comments")):
        m = re.search(pat, text, re.I)
        if m:
            n = _num(m.group(1))
            if n is not None:
                out[key] = n
    return out


def _spoken_content(video_file: str) -> list[str]:
    """Whisper transcription (Groq) → keywords from what's SAID in
    the video. The strongest learning signal — it's what the
    competitor actually tells their audience."""
    import llm
    if not video_file or not Path(video_file).exists():
        return []
    tr = llm.transcribe(video_file)
    if not tr.get("ok"):
        return []
    from collections import Counter
    words = Counter(w.lower() for w in re.findall(
        r"[a-zA-Z]{4,}", tr["text"]) if w.lower() not in
        ("with", "this", "that", "have", "from", "what", "they", "their",
         "just", "like", "going", "know", "really", "about", "there"))
    return [w for w, c in words.most_common(10) if c >= 2]


def learn(url: str, username: str = "", password: str = "",
          video_file: str = "") -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"))
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(5)

            # login wall? retry logged-in if creds given
            body = page.content()
            if ("Log in" in body and "og:description" not in body
                    and username):
                bp2 = __import__("browser_poster")
                bp2.login(page, username, password)
                page.goto(url, wait_until="domcontentloaded",
                            timeout=60_000)
                time.sleep(5)
                body = page.content()

            desc = ""
            m = re.search(r'property="og:description" content="([^"]*)"',
                          body)
            if m:
                desc = m.group(1)

            hashtags = sorted(set(re.findall(r"#(\w+)", desc)))
            counts = _counts_from_text(desc)

            # fallback: visible "X views" aria labels
            if "views" not in counts:
                m = re.search(r'aria-label="([\d.,]+\s*[KMB]?) views"', body)
                if m:
                    n = _num(m.group(1))
                    if n is not None:
                        counts["views"] = n

            caption = desc
            # og:description often starts "X views, Y likes ... — caption"
            m = re.search(r"(?:—|–|\bFiled under\b|on\s+\w+.*?:)\s*(.+)$",
                          desc, re.S)
            if m:
                caption = m.group(1)

            insights = []
            views = counts.get("views")
            likes = counts.get("likes")
            if views and likes:
                ratio = views / max(likes, 1)
                if ratio < 25:
                    insights.append("High like-rate — strong hook, "
                                      "audience loves it")
                else:
                    insights.append("Views high but likes low — "
                                      "watchable but weak CTA/relatability")
            if len(hashtags) <= 5:
                insights.append(f"Uses only {len(hashtags)} focused "
                                  "hashtags (2026 best practice)")
            else:
                insights.append(f"Uses {len(hashtags)} hashtags — "
                                  "many; fewer focused tags trend better")
            if not counts:
                insights.append("Could not read counts — Instagram may "
                                  "have shown a login wall; retry with "
                                  "credentials")

            # spoken content: transcribe a local copy if provided
            spoken = _spoken_content(video_file)
            if spoken:
                insights.append("Said in the video (Whisper): "
                                  + ", ".join(spoken[:8]))

            return {"url": url, "hashtags": hashtags,
                    "counts": counts, "caption": caption[:500],
                    "spoken_keywords": spoken,
                    "insights": insights}
        finally:
            browser.close()


def save_learned_tags(hashtags: list[str]) -> list[str]:
    """Merge learned hashtags into trending_tags.json under
    '_learned' so future SEO picks them up."""
    f = BASE / "trending_tags.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    existing = data.get("_learned", [])
    merged = list(dict.fromkeys(existing + [h.lower() for h in hashtags]))
    data["_learned"] = merged[:30]
    data["_learned_updated"] = time.strftime("%Y-%m-%d")
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    return merged


def fetch_transcript(url: str) -> dict:
    """Transcript of a YouTube video via yt-dlp (agent-reach's
    youtube backend) — works without any API key when the video has
    captions. Extracts keywords for the Learn feature."""
    import subprocess
    if "youtube.com" not in url and "youtu.be" not in url:
        return {"ok": False, "error": "transcript path works for "
                                       "YouTube URLs (reels: use visual "
                                       "analysis)"}
    try:
        r = subprocess.run(
            ["yt-dlp", "--skip-download", "--subtitles-lang", "en",
             "--subtitles-format", "json3", "--print-json", url],
            capture_output=True, text=True, timeout=90)
        d = json.loads(r.stdout or "{}")
    except Exception as e:
        return {"ok": False, "error": f"yt-dlp failed: {str(e)[:120]}"}
    subs = (d.get("subtitles") or {}).get("en") or \
        (d.get("automatic_captions") or {}).get("en")
    if not subs:
        return {"ok": False, "error": "no English captions on this video"}
    # json3: events[].segs[].utf8
    text = " ".join(
        s.get("utf8", "") for ev in subs for s in (ev.get("segs") or []))
    text = re.sub(r"\s+", " ", text).strip()
    # keywords: words appearing 2+ times
    from collections import Counter
    words = Counter(w.lower() for w in re.findall(
        r"[a-zA-Z]{4,}", text) if w.lower() not in
        ("with", "this", "that", "have", "from", "what", "they", "their",
         "just", "like", "going", "know", "really", "about"))
    keywords = [w for w, c in words.most_common(15) if c >= 2]
    return {"ok": True, "title": d.get("title", ""), "keywords": keywords,
              "transcript_sample": text[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--video", default="",
                    help="local video file (transcribes spoken content)")
    ap.add_argument("--save-tags", action="store_true",
                    help="merge learned hashtags into trending_tags.json")
    args = ap.parse_args()
    out = learn(args.url, args.username, args.password, args.video)
    if args.save_tags and out["hashtags"]:
        out["saved_tags"] = save_learned_tags(out["hashtags"])
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
