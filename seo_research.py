"""Live SEO research: scrape today's top-performing AI videos via YouTube API,
frequency-analyze their tags/title-words/hashtags, print winners.
Run anytime; feed results into captions.py."""
from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
_ENV = BASE / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ["YOUTUBE_API_KEY"]
QUERIES = ["AI generated video", "sora ai", "veo 3 ai video", "ai shorts funny",
           "ai animation", "ai baby"]
DAYS = int(os.environ.get("SEARCH_DAYS", "14"))

STOP = {"the", "and", "for", "you", "your", "with", "this", "that", "video",
        "shorts", "short", "from", "are", "was", "not", "but", "how", "what",
        "new", "best", "top", "get", "all", "can", "will", "our", "has", "had"}


def main() -> None:
    after = (datetime.utcnow() - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in QUERIES:
        r = requests.get("https://www.googleapis.com/youtube/v3/search",
                         params={"part": "snippet", "q": q, "type": "video",
                                 "order": "viewCount", "publishedAfter": after,
                                 "maxResults": 25, "key": KEY}, timeout=30).json()
        ids += [i["id"]["videoId"] for i in r.get("items", []) if i.get("id", {}).get("videoId")]
    ids = list(dict.fromkeys(ids))[:50]
    print(f"Analyzing {len(ids)} top-view AI videos from last {DAYS} days...\n")

    tag_counter, hash_counter, word_counter, bigram_counter = Counter(), Counter(), Counter(), Counter()
    views_total = {}
    for i in range(0, len(ids), 50):
        d = requests.get("https://www.googleapis.com/youtube/v3/videos",
                         params={"part": "snippet,statistics", "id": ",".join(ids[i:i+50]),
                                 "key": KEY}, timeout=30).json()
        for it in d.get("items", []):
            sn = it["snippet"]
            views = int(it.get("statistics", {}).get("viewCount") or 0)
            for t in sn.get("tags") or []:
                t = t.lower().strip()
                if 2 <= len(t) <= 40:
                    tag_counter[t] += 1
                    views_total[t] = views_total.get(t, 0) + views
            text = f"{sn['title']} {sn.get('description', '')}"
            for h in set(h.lower() for h in __import__('re').findall(r"#\w{2,30}", text)):
                hash_counter[h] += 1
            words = [w.lower() for w in __import__('re').findall(r"[A-Za-z]{3,}", sn['title'])]
            seq = [w for w in words if w not in STOP]
            word_counter.update(seq)
            bigram_counter.update(f"{a} {b}" for a, b in zip(seq, seq[1:]))

    def table(title, counter, n=30):
        print(f"\n=== TOP {n} {title} ===")
        for k, c in counter.most_common(n):
            v = views_total.get(k, "")
            print(f"{c:4d}x  {f'{v:,}' if v != '' else '':>12}  {k}")

    table("TAGS (freq | total views across videos using it)", tag_counter)
    table("HASHTAGS in titles/descriptions", hash_counter, 20)
    table("TITLE KEYWORDS", word_counter, 20)
    table("TITLE BIGRAMS", bigram_counter, 15)


if __name__ == "__main__":
    main()
