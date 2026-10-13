"""Instagram cross-poster with SCHEDULED publishing.

Two modes:
  (default)            ENQUEUE - scan videos/done/*.json, assign each item a
                       future publish slot (ig_slots below), store in ig_queue.json
  --post-due           POSTER  - publish queued items whose time has come

Called from Task Scheduler:
  Daily 10:00 run_daily.ps1      -> enqueue mode
  08:00/11:30/14:30/17:30/20:15  -> --post-due mode

Credentials/session: .env INSTAGRAM_SESSIONID + ig_session.json (rotating).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
VIDEOS_DIR = BASE / "videos"
PENDING_DIR = VIDEOS_DIR / "pending"
DONE_DIR = VIDEOS_DIR / "done"
ARCHIVE_DIR = DONE_DIR / "ig_archived"
STATE_FILE = BASE / "ig_state.json"
QUEUE_FILE = BASE / "ig_queue.json"
SESSION_FILE = BASE / "ig_session.json"
DEVICE_FILE = BASE / "ig_device.json"
PAUSE_FILE = BASE / "pause_until.txt"

sys.path.insert(0, str(BASE))
from captions import generate_instagram  # noqa: E402

REEL_MAX_SECONDS = 90
# ponytail: STRICT 1 reel/day. Buffer 9.6M-post study: evening 6-11pm peaks,
# Wed/Thu best days. One 18:00 slot daily - cadence > day-picking at 1/day.
IG_SLOTS = ["18:00"]
MIN_LEAD_HOURS = 2

# load .env
_ENV = BASE / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

USER = os.environ.get("INSTAGRAM_USERNAME", "")
PWD = os.environ.get("INSTAGRAM_PASSWORD", "")
SESSION_ID = os.environ.get("INSTAGRAM_SESSIONID", "")


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def connect():
    if os.environ.get("INSTAGRAM_GRAPH_TOKEN"):
        from instagram_graph import GraphClient
        print("Using OFFICIAL Instagram Graph API (page-linked account).")
        return GraphClient()
    from instagrapi import Client
    cl = Client()
    cl.delay_range = [2, 6]
    if DEVICE_FILE.exists():
        cl.set_device(json.loads(DEVICE_FILE.read_text(encoding="utf-8")))
    if SESSION_FILE.exists():
        try:
            cl.load_settings(str(SESSION_FILE))
            cl.get_timeline_feed()
            print("Instagram session restored.")
            return cl
        except Exception as exc:
            print(f"Session invalid ({exc}), re-authenticating...")
    if SESSION_ID:
        print("Logging in with browser sessionid...")
        cl.login_by_sessionid(SESSION_ID)
        cl.dump_settings(str(SESSION_FILE))
        print("Logged in via sessionid.")
        return cl
    if USER and PWD:
        cl.login(USER, PWD)
        cl.dump_settings(str(SESSION_FILE))
        print(f"Logged in as {USER}.")
        return cl
    sys.exit("ERROR: no Instagram auth available (.env)")


def _make_cover(video_path: str, title: str) -> str:
    """Cover with hook text in the 3:4 grid-safe center (FRAME framework A).
    Bold text survives the 9:16 reel / 4:5 feed / 3:4 grid crops."""
    import subprocess
    cover = str(Path(video_path).with_suffix(".cover.jpg"))
    words = title.split()
    # ponytail: max 3 words on a cover - legibility > cleverness at 120px
    text = " ".join(words[:3]).upper()[:24] or "AI"
    vf = (
        f"drawtext=text='{text}':fontcolor=white:fontsize=120:box=1:"
        f"boxcolor=black@0.55:boxborderw=24:x=(w-text_w)/2:y=(h-text_h)/2"
    )
    subprocess.run([
        str(BASE / "bin" / "ffmpeg.exe"), "-y", "-ss", "1", "-i", video_path,
        "-vframes", "1", "-vf", vf, "-q:v", "3", cover,
    ], check=True, capture_output=True, timeout=120)
    return cover


def post_one(cl, meta: dict) -> str:
    caption = generate_instagram(meta)
    path = meta["file"]
    dur = meta.get("duration") or 0
    if not (0 < dur <= REEL_MAX_SECONDS):
        # ponytail: IG hard-rejects >90.5s uploads (TranscodeError) - guard here
        raise ValueError(f"duration {dur:.0f}s exceeds IG reel cap {REEL_MAX_SECONDS}s")
    thumb = _make_cover(path, meta.get("title", ""))
    media = cl.clip_upload(path, caption=caption, thumbnail=thumb,
                           share_to_threads=False)
    return f"reel:{media.pk}"


def next_free_slot(used: set[str]) -> datetime:
    """One 18:00 slot per day, strictly sequential days."""
    earliest = datetime.now().astimezone() + timedelta(hours=MIN_LEAD_HOURS)
    for _ in range(60):
        for hhmm in IG_SLOTS:
            h, m = map(int, hhmm.split(":"))
            dt = datetime.combine(earliest.date(), datetime.min.time(),
                                  tzinfo=earliest.tzinfo).replace(hour=h, minute=m)
            key = dt.strftime("%Y-%m-%d %H:%M")
            if dt > earliest and key not in used:
                return dt
        earliest = datetime.combine(earliest.date() + timedelta(days=1),
                                     datetime.min.time(), tzinfo=earliest.tzinfo)
    raise RuntimeError("no free IG slot")


def enqueue_mode(state: dict) -> None:
    """Assign slots to everything new in done/, archive the jsons."""
    queue = load_json(QUEUE_FILE, [])
    used = {q["publish_at"] for q in queue}
    pendings = sorted(DONE_DIR.glob("*.json")) if DONE_DIR.exists() else []
    posted = set(state["posted"])
    added = 0
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for p in pendings:
        meta = json.loads(p.read_text(encoding="utf-8"))
        if meta.get("source_id") in posted:
            p.unlink(missing_ok=True)
            continue
        if not Path(meta["file"]).exists():
            print(f"[SKIP] missing file: {meta['file']}")
            continue
        if (meta.get("duration") or 0) > REEL_MAX_SECONDS:
            # ponytail: IG hard cap 90.5s - don't queue what it will reject
            print(f"[IG-SKIP] too long for reel ({(meta.get('duration') or 0):.0f}s): "
                  f"{meta['title'][:50]}")
            continue
        slot = next_free_slot(used)
        key = slot.strftime("%Y-%m-%d %H:%M")
        used.add(key)
        queue.append({
            "source_id": meta["source_id"],
            "title": meta["title"],
            "source_url": meta.get("source_url", ""),
            "file": meta["file"],
            "duration": meta.get("duration"),
            "publish_at": key,
        })
        dest = ARCHIVE_DIR / p.name
        if dest.exists():
            dest = ARCHIVE_DIR / f"{p.stem}_{int(time.time())}{p.suffix}"
        p.rename(dest)
        save_json(QUEUE_FILE, queue)
        added += 1
        print(f"[QUEUED] {key} <- {meta['title'][:60]}")
    print(f"Enqueue summary: {added} added, {len(queue)} total in queue")


def post_direct_mode(state: dict) -> None:
    """Post the newest pending download immediately (bypasses queue)."""
    pendings = sorted(PENDING_DIR.glob("*.json")) if PENDING_DIR.exists() else []
    shorts = [p for p in pendings
              if json.loads(p.read_text(encoding="utf-8")).get("kind") == "short"]
    pick = (shorts or pendings)
    if not pick:
        print("Nothing pending to post directly. Run /dl first.")
        return
    p = sorted(pick, key=lambda x: x.stat().st_mtime)[-1]
    meta = json.loads(p.read_text(encoding="utf-8"))

    cl = None
    try:
        cl = connect()
    except Exception as exc:
        print(f"[IG LOGIN FAILED] {exc}")
        print("Fix: log into instagram.com, export a fresh 'sessionid' cookie"
              " (Cookie-Editor extension), paste it to the assistant to update .env.")
        return
    try:
        result = post_one(cl, meta)
        state["posted"].append(meta["source_id"])
        save_json(STATE_FILE, state)
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = ARCHIVE_DIR / p.name
        if dest.exists():
            dest = ARCHIVE_DIR / f"{p.stem}_{int(time.time())}{p.suffix}"
        p.rename(dest)
        try:
            Path(meta["file"]).unlink(missing_ok=True)   # already published on IG only
        except OSError:
            pass
        print(f"[IG OK] {result} <- {meta['title'][:60]}")
    except Exception as exc:
        print(f"[IG FAIL] {meta.get('title', '')[:50]}: {exc}")
    try:
        cl.dump_settings(str(SESSION_FILE))
    except Exception as exc:
        print(f"WARN: could not save refreshed session: {exc}")


def post_due_mode(state: dict) -> None:
    queue = load_json(QUEUE_FILE, [])
    now = datetime.now().astimezone()
    due = [q for q in queue
           if datetime.strptime(q["publish_at"], "%Y-%m-%d %H:%M").astimezone() <= now]
    if not due:
        print("Instagram: nothing due right now.")
        return

    try:
        cl = connect()
    except Exception as exc:
        print(f"[IG LOGIN FAILED] {exc}")
        print("Fix: export a fresh 'sessionid' from instagram.com cookies"
              " (Cookie-Editor) and update INSTAGRAM_SESSIONID in .env.")
        return

    still_queue, ok, fail = [], 0, 0
    today = datetime.now().astimezone().date().isoformat()
    last_post_date = state.get("last_ig_post_date", "")
    if last_post_date == today:
        print(f"Instagram: already posted today ({today}), skipping.")
        save_json(QUEUE_FILE, queue)
        return
    for q in sorted(queue, key=lambda x: x["publish_at"]):
        if q in due and ok > 0:
            break   # 1/day cap hit - keep the rest (due incl.) queued for tomorrow
        if q not in due:
            still_queue.append(q)
            continue
        if not Path(q["file"]).exists():
            print(f"[SKIP] missing file: {q['file']}")
            still_queue.append(q)   # keep missing-file items for later retry
            continue
        try:
            result = post_one(cl, q)
            state["posted"].append(q["source_id"])
            state["last_ig_post_date"] = today
            save_json(STATE_FILE, state)
            ok += 1
            print(f"[IG OK] {result} (was scheduled {q['publish_at']}) <- {q['title'][:60]}")
            # ponytail: hard 1/day cap - new IG accounts get throttled at 2+/day
            print("Daily limit reached (1 post/day) - remaining items stay queued.")
            break
        except Exception as exc:
            fail += 1
            print(f"[IG FAIL] {q['title'][:50]}: {exc}")
            time.sleep(10)

    save_json(STATE_FILE, state)
    save_json(QUEUE_FILE, still_queue)
    try:
        cl.dump_settings(str(SESSION_FILE))   # persist rotated cookies
    except Exception as exc:
        print(f"WARN: could not save refreshed session: {exc}")
    print(f"\nInstagram summary: {ok} posted, {fail} failed, {len(still_queue)} still queued")


def _paused() -> bool:
    if PAUSE_FILE.exists():
        try:
            if datetime.strptime(PAUSE_FILE.read_text(encoding="utf-8").strip(),
                                 "%Y-%m-%d") >= datetime.now():
                print(f"Paused until {PAUSE_FILE.read_text().strip()} - skipping Instagram posting.")
                return True
        except ValueError:
            pass
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-due", action="store_true")
    parser.add_argument("--direct", action="store_true",
                        help="immediately post the newest pending download instead of queueing")
    args = parser.parse_args()

    state = load_json(STATE_FILE, {"posted": []})
    if args.post_due and not args.direct:
        if _paused():
            return 0
        post_due_mode(state)
    elif args.direct:
        post_direct_mode(state)
    else:
        enqueue_mode(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
