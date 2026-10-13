"""Download trending/recent AI videos using yt-dlp.

Splits candidates into SHORTS (<=60s) and VIDEOS (61-MAX_DURATION).
Writes one pending JSON per video into videos/pending/ consumed by upload_youtube.py.
Run:
  .venv\\Scripts\\python.exe download_trending.py            # env-configured counts
  ... download_trending.py --shorts 5 --videos 5             # override
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests
import yt_dlp

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
VIDEOS_DIR = BASE / "videos"
PENDING_DIR = VIDEOS_DIR / "pending"
STATE_FILE = BASE / "downloaded.json"

# load .env (KEY=VALUE lines)
_ENV = BASE / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

REQUIRE_AI_CONTENT = os.environ.get("REQUIRE_AI_CONTENT", "1") == "1"
REQUIRE_CC_LICENSE = os.environ.get("REQUIRE_CC_LICENSE", "1") == "1"   # only reusable videos
AI_QUERIES = [
    # top niches by live demand 2026-08-24 (analytics_report.py Top5 views)
    "ai comedy video",          # #1 132M - ai comedy skits
    "ai animals funny",         # #3 101M - ai animals (NEW, was missing)
    "ai football",              # #2 103M - ai sports (NEW)
    "ai baby funny",            # #4 72M - ai babies/kids
    "ai story hindi",           # #8 21M - ai storytelling
    "sora ai video",            # high production value source
    "veo ai generated",
    # CC-friendly sources (creative commons reuse allowed)
    "ai generated video creative commons",
    "free stock footage ai",
    "public domain animation",
]
SEARCH_DAYS = int(os.environ.get("SEARCH_DAYS", "14"))
MAX_DURATION = int(os.environ.get("MAX_DURATION", "300"))   # seconds, videos
SHORTS_MAX_DURATION = 60                                    # seconds
MIN_DURATION = 15                                           # seconds
# ponytail: viral floor - repost only proven winners (source already has the
# views we want our copy to catch). 250k min, 1M+ preferred. 0 disables.
VIRAL_FLOOR_VIEWS = int(os.environ.get("VIRAL_FLOOR_VIEWS", "250000"))

AI_KEYWORDS = ["ai ", "a.i.", "artificial intelligence", "ai-", "-ai",
               " sora", "veo", "midjourney", "runwayml", "runway ",
               "gen-3", "gen-4", "kling", "pika labs", "luma", "hailuo",
               "stable diffusion", "neural render", "deepfake"]


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"downloaded": [], "skipped": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _looks_ai(entry: dict) -> bool:
    text = " ".join([
        str(entry.get("title") or ""),
        str(entry.get("description") or ""),
        str(entry.get("channel") or ""),
    ]).lower()
    return any(k in text for k in AI_KEYWORDS)


def _iso8601_seconds(iso: str) -> int:
    import re
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def find_candidates(api_key: str | None) -> list[dict]:
    """AI-focused search ranked by views; falls back to trending then yt-dlp."""
    if api_key:
        import datetime as dt
        after = (dt.datetime.utcnow() - dt.timedelta(days=SEARCH_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids, meta = [], {}
        for q in AI_QUERIES:
            try:
                r = requests.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={"part": "snippet", "q": q, "type": "video", "order": "viewCount",
                            "publishedAfter": after, "maxResults": 25, "key": api_key},
                    timeout=30).json()
                for it in r.get("items", []):
                    vid = it.get("id", {}).get("videoId")
                    if not vid or vid in meta:
                        continue
                    sn = it["snippet"]
                    meta[vid] = {
                        "id": vid,
                        "title": sn["title"],
                        "description": sn.get("description") or "",
                        "channel": sn.get("channelTitle") or "",
                        "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                        "views": 0,
                    }
                    ids.append(vid)
            except Exception as exc:
                print(f"Search '{q}' failed: {exc}")
        if ids:
            for i in range(0, len(ids), 50):
                chunk = ids[i:i + 50]
                try:
                    d = requests.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={"part": "contentDetails,statistics,status",
                                "id": ",".join(chunk), "key": api_key},
                        timeout=30).json()
                    for it in d.get("items", []):
                        e = meta[it["id"]]
                        e["duration"] = _iso8601_seconds(it["contentDetails"]["duration"])
                        e["views"] = int(it.get("statistics", {}).get("viewCount") or 0)
                        e["license"] = it.get("status", {}).get("license", "youtube")
                        e["channel"] = it["snippet"].get("channelTitle", "") if "snippet" in it else e.get("channel", "")
                except Exception as exc:
                    print(f"Durations fetch failed: {exc}")
            entries = [e for e in meta.values() if e.get("duration")]
            if REQUIRE_CC_LICENSE:
                before = len(entries)
                entries = [e for e in entries if e.get("license") == "creativeCommon"]
                print(f"CC license filter: {before} -> {len(entries)} reusable videos")
            ai_hits = [e for e in entries if _looks_ai(e)]
            if REQUIRE_AI_CONTENT and ai_hits:
                ai_hits.sort(key=lambda e: e.get("views") or 0, reverse=True)
                print(f"AI+CC search: {len(ai_hits)} candidates (of {len(entries)} CC)")
                return ai_hits
            if entries:
                entries.sort(key=lambda e: e.get("views") or 0, reverse=True)
                if REQUIRE_AI_CONTENT:
                    print(f"No AI+CC match today - using {len(entries)} general CC videos instead")
                else:
                    print(f"CC search: {len(entries)} candidates")
                return entries
        print("API search empty, falling back...")

    url = f"ytsearch40:AI generated video"
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = [e for e in (info.get("entries") or []) if e]
    if REQUIRE_AI_CONTENT:
        entries = [e for e in entries if _looks_ai(e)]
    return entries


def _add_hook(path: Path) -> None:  # ponytail: disabled — WAIT FOR IT overlay triggers IG spam filter, 0 views
    pass

def download(entry: dict) -> Path | None:
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    outtmpl = str(VIDEOS_DIR / "%(id)s.%(ext)s")
    def _cc_guard(info, *, incomplete=False):
        if not REQUIRE_CC_LICENSE:  # ponytail: allow trending non-CC when REQUIRE_CC_LICENSE=0
            return None
        lic = info.get("license")
        if lic and "creative" not in str(lic).lower():
            return f"explicitly non-CC license: {lic}"
        return None

    opts = {
        "quiet": False,
        "no_warnings": True,
        "outtmpl": outtmpl,
        # ponytail: height<=1920 allows vertical 1080p (1080x1920). The old
        # <=720 cap excluded ALL vertical 720p+ (their height is 1280/1920),
        # silently forcing 360p downloads - IG deprioritizes low-res reels.
        "format": "bv*[height<=1920][ext=mp4]+ba[ext=m4a]/b[height<=1920][ext=mp4]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "ffmpeg_location": str(BASE / "bin" / "ffmpeg.exe"),
        "socket_timeout": 30,
        "retries": 5,
        "concurrent_fragment_downloads": 4,
        "match_filter": _cc_guard,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([entry["webpage_url"]])
    except Exception as exc:
        print(f"download failed {entry.get('id')}: {exc}")
        return None
    path = VIDEOS_DIR / f"{entry['id']}.mp4"
    if path.exists():
        _add_hook(path)
    return path if path.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--shorts", type=int, default=int(os.environ.get("SHORTS_COUNT", "2")))
    parser.add_argument("--videos", type=int, default=int(os.environ.get("VIDEO_COUNT", "3")))
    args = parser.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    state = load_state()
    done = set(state["downloaded"]) | set(state["skipped"])
    candidates = [e for e in find_candidates(api_key) if e and e.get("id") not in done]

    topic = os.environ.get("TOPIC_KEYWORDS", "").strip().lower()
    if topic:
        kws = [k.strip() for k in topic.split(",") if k.strip()]
        before = len(candidates)
        candidates = [e for e in candidates
                      if any(k in f"{e.get('title', '')} {e.get('description', '')}".lower()
                              for k in kws)]
        print(f"Topic filter '{topic}': {len(candidates)}/{before} videos match")

    # ponytail: viral floor - only sources proven to pull big views. Relaxes
    # once per pass (floor/10) if pool is empty so the bot never stalls.
    if VIRAL_FLOOR_VIEWS > 0:
        for floor in (VIRAL_FLOOR_VIEWS, VIRAL_FLOOR_VIEWS // 10, 0):
            viral = [e for e in candidates if (e.get("views") or 0) >= floor]
            if viral or floor == 0:
                if floor != VIRAL_FLOOR_VIEWS and floor > 0:
                    print(f"Viral floor {VIRAL_FLOOR_VIEWS:,} -> relaxed to {floor:,} ({len(viral)} candidates)")
                elif floor == 0:
                    print(f"Viral floor relaxed to off ({len(viral)} candidates)")
                candidates = viral
                break
        else:
            candidates = []
        print(f"Viral pool: {len(candidates)} sources >= floor views")

    # ponytail: AVD>50s Shorts avg 4.1M views (PaddyGalloway/YouTube data) -
    # prefer 45-60s sources, then 30-45s, then rest. Sort is stable per bucket.
    def _short_rank(e: dict) -> tuple[int, int]:
        d = e.get("duration") or 0
        bucket = 0 if 45 <= d <= 60 else (1 if 30 <= d < 45 else 2)
        return (bucket, -(e.get("views") or 0))
    shorts_pool = sorted((e for e in candidates if MIN_DURATION <= (e.get("duration") or 0) <= SHORTS_MAX_DURATION),
                          key=_short_rank)  # ponytail: length bucket > views
    videos_pool = sorted((e for e in candidates if SHORTS_MAX_DURATION < (e.get("duration") or 0) <= MAX_DURATION),
                          key=lambda e: e.get("views") or 0, reverse=True)
    print(f"Pools -> shorts: {len(shorts_pool)}, videos: {len(videos_pool)}")

    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    targets = [("short", args.shorts, shorts_pool), ("video", args.videos, videos_pool)]

    for kind, want, pool in targets:
        got = 0
        for e in pool:
            if got >= want:
                break
            print(f"[{kind}] Downloading ({got + 1}/{want}) [{(e.get('views') or 0):,} views]: {e.get('title', '')[:70]}")
            path = download(e)
            if not path:
                state["skipped"].append(e["id"])
                continue
            meta = {
                "kind": kind,
                "source_id": e["id"],
                "source_url": e["webpage_url"],
                "title": (e.get("title") or "AI Video")[:100],
                "description": (
                    f"{e.get('title')}\n\nSource: {e['webpage_url']}\nAll rights belong to the original creator."
                )[:5000],
                "file": str(path),
                "duration": e["duration"],
            }
            (PENDING_DIR / f"{e['id']}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            state["downloaded"].append(e["id"])
            got += 1
        save_state(state)
        print(f"[{kind}] downloaded {got}/{want}")

    # clean stray mp4 files NOT referenced by any pending json or IG queue
    referenced = {Path(json.loads(p.read_text(encoding="utf-8"))["file"]).name
                  for p in PENDING_DIR.glob("*.json")}
    # ponytail: keep IG queue files, otherwise next IG post SKIPs
    qfile = BASE / "ig_queue.json"
    if qfile.exists():
        try:
            for q in json.loads(qfile.read_text(encoding="utf-8")):
                referenced.add(Path(q.get("file","")).name)
        except Exception:
            pass
    for old in VIDEOS_DIR.glob("*.mp4"):
        if old.name not in referenced and not old.name.endswith("_ig.mp4"):
            try:
                old.unlink()
            except OSError:
                pass
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
