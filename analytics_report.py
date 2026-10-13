"""Viewer-interest report:
1) Per-video retention ('Stayed to watch' % = averageViewPercentage)
2) Live niche demand: which AI video types get the most views right now
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
os.chdir(BASE)

_ENV = BASE / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ["YOUTUBE_API_KEY"]


def my_videos(svc):
    ch = svc.channels().list(part="contentDetails", mine=True).execute()
    pl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    vids = svc.playlistItems().list(part="snippet", playlistId=pl, maxResults=50).execute()
    ids = [i["snippet"]["resourceId"]["videoId"] for i in vids["items"]]
    if not ids:
        return []
    d = svc.videos().list(part="snippet,contentDetails,statistics",
                          id=",".join(ids)).execute()
    out = []
    for it in d["items"]:
        dur = it["contentDetails"]["duration"]
        import re
        m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", dur or "")
        h, mi, s = (int(x) if x else 0 for x in m.groups()[1:]) if m else (0, 0, 0)
        secs = h * 3600 + mi * 60 + s
        out.append({
            "id": it["id"],
            "title": it["snippet"]["title"],
            "secs": secs,
            "views": int(it.get("statistics", {}).get("viewCount") or 0),
            "privacy": it.get("status", {}).get("privacyStatus", "?"),
        })
    return out


def retention_report(vids):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]
    creds = Credentials.from_authorized_user_file(str(BASE / "token.json"), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    svc = build("youtubeAnalytics", "v2", credentials=creds)

    print("=" * 70)
    print("YOUR VIDEOS - VIEWER INTEREST")
    print("=" * 70)
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%d")
    r = svc.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="views,averageViewDuration,averageViewPercentage",
        dimensions="video", sort="-views", maxResults=50,
    ).execute()
    rows = {r0[0]: r0[1:] for r0 in r.get("rows", [])}
    hdr = f"{'Video':<42}{'Type':<7}{'Views':>6}  {'Stayed%':>8}  {'AvgWatch':>9}"
    print(hdr)
    print("-" * len(hdr))
    for v in sorted(vids, key=lambda x: -x["views"]):
        kind = "short" if v["secs"] <= 90 else "video"
        row = rows.get(v["id"])
        if row:
            views, avg_dur, avg_pct = row  # ponytail: drop likes, query returns 3 metrics
            print(f"{v['title'][:41]:<42}{kind:<7}{views:>6}  {avg_pct:>7.1f}%  {int(avg_dur):>7}s")
        else:
            print(f"{v['title'][:41]:<42}{kind:<7}{v['views']:>6}  {'n/a':>8}  {'-':>9}")


def niche_demand():
    print()
    print("=" * 70)
    print("WHAT AI CONTENT DO USERS WANT? (live demand, last 14 days)")
    print("=" * 70)
    niches = {
        "AI babies/kids": ["ai baby", "ai baby funny"],
        "AI animals": ["ai animal", "ai animals funny"],
        "AI cooking/ASMR": ["ai cooking", "asmr cooking ai"],
        "AI storytelling": ["ai story hindi", "ai storytelling"],
        "AI cinematic/film": ["ai film trailer", "cinematic ai video"],
        "AI gods/mythology": ["ai mahadev", "ai god video"],
        "AI sports": ["ai football", "sora sports"],
        "AI travel/nature": ["ai nature video", "ai travel"],
        "AI comedy skits": ["ai comedy video", "funny ai shorts"],
        "AI satisfying/ASMR": ["satisfying ai video", "oddly satisfying ai"],
    }
    after = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = []
    for name, queries in niches.items():
        views, count = [], 0
        for q in queries:
            r = requests.get("https://www.googleapis.com/youtube/v3/search",
                             params={"part": "snippet", "q": q, "type": "video",
                                     "order": "viewCount", "publishedAfter": after,
                                     "maxResults": 15, "key": KEY}, timeout=30).json()
            ids = [i["id"]["videoId"] for i in r.get("items", []) if i.get("id", {}).get("videoId")]
            if ids:
                d = requests.get("https://www.googleapis.com/youtube/v3/videos",
                                 params={"part": "statistics", "id": ",".join(ids),
                                         "key": KEY}, timeout=30).json()
                for it in d.get("items", []):
                    v = int(it.get("statistics", {}).get("viewCount") or 0)
                    if v > 1000:          # ignore noise
                        views.append(v)
                        count += 1
        if views:
            views.sort(reverse=True)
            top = sum(views[:5])
            med = views[len(views)//2]
            results.append((name, top, med, count))
    results.sort(key=lambda x: -x[1])
    print(f"{'Niche':<22}{'Top5 views':>14}{'Median':>12}{'Videos>1k':>11}")
    print("-" * 60)
    for name, top, med, count in results:
        print(f"{name:<22}{top:>14,}{med:>12,}{count:>11}")
    print("\n=> Higher 'Top5 views' = users are binge-watching that niche NOW")


if __name__ == "__main__":
    from upload_youtube import get_service
    data_svc = get_service()
    vids = my_videos(data_svc)
    retention_report(vids)
    niche_demand()
