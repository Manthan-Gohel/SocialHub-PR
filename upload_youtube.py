"""Upload pending videos to YouTube with SCHEDULED publish times.

Every file in videos/pending/*.json gets uploaded as PRIVATE with a
publishAt slot. Slots roll forward day by day, so content prepared today
goes live tomorrow or later (always >= 1 day ahead).

Preferred local times:
  shorts : 07:00 10:00 13:00 16:00 19:00
  videos : 08:30 12:30 15:30 18:30 21:00

Run: .venv\\Scripts\\python.exe upload_youtube.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
VIDEOS_DIR = BASE / "videos"
PENDING_DIR = VIDEOS_DIR / "pending"
DONE_DIR = VIDEOS_DIR / "done"

sys.path.insert(0, str(BASE))
from captions import generate_youtube  # noqa: E402
TOKEN_FILE = BASE / "token.json"
CLIENT_SECRET = BASE / "client_secret.json"
STATE_FILE = BASE / "schedule_state.json"
PAUSE_FILE = BASE / "pause_until.txt"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",      # uploads + thumbnails
    "https://www.googleapis.com/auth/youtube.force-ssl",   # update/delete videos
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # retention stats
]

# ponytail: day/time weights from Buffer 1.8M-video study (2026-07).
# Long-form: Sun/Tue/Mon mornings peak (Sun 10am #1, Wed/Thu afternoons worst).
# Shorts: Fri/Thu/Sat evenings peak (Fri 4pm #1); AVD>50s matters more than timing.
SLOTS = {
    "short": ["18:00", "19:00", "20:00", "16:00"],   # evening-first
    "video": ["09:00", "10:00", "08:30", "12:30"],   # morning-first
}
DAY_WEIGHT = {
    "video": {"Sun": 0, "Tue": 1, "Mon": 1, "Fri": 2, "Sat": 3, "Wed": 3, "Thu": 3},
    "short": {"Fri": 0, "Thu": 1, "Sat": 1, "Sun": 2, "Wed": 2, "Tue": 3, "Mon": 3},
}
MIN_LEAD_HOURS = 3          # never schedule sooner than this from now


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"used_slots": [], "uploaded": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None  # dead/revoked refresh token -> full re-auth
        if not creds:
            if not CLIENT_SECRET.exists():
                sys.exit("ERROR: client_secret.json missing.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            raw = json.loads(CLIENT_SECRET.read_text(encoding="utf-8"))
            creds = flow.run_local_server(port=8080 if "web" in raw else 0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def next_free_slot(kind: str, used: set[str]) -> datetime:
    """Best slot per research: day-weight first, then time-of-day order."""
    earliest = datetime.now().astimezone() + timedelta(hours=MIN_LEAD_HOURS)
    for _ in range(60):  # look ahead max 60 days
        # build (day_weight, day_offset) so better days come first
        days = sorted(
            range(0, 8),
            key=lambda d: (DAY_WEIGHT[kind].get(
                (earliest + timedelta(days=d)).strftime("%a"), 3), d),
        )
        for d in days:
            day = (earliest + timedelta(days=d)).date()
            for hhmm in SLOTS[kind]:
                h, m = map(int, hhmm.split(":"))
                dt = datetime.combine(day, datetime.min.time(),
                                      tzinfo=earliest.tzinfo).replace(hour=h, minute=m)
                if dt > earliest and dt.strftime("%Y-%m-%d %H:%M") not in used:
                    return dt
    raise RuntimeError("no free slot found")


def upload_one(service, meta: dict, publish_at_utc: str) -> str:
    seo = generate_youtube(meta)
    body = {
        "snippet": {
            "title": seo["title"],
            "description": seo["description"],
            "tags": seo["tags"],
            "categoryId": "23",  # ponytail: Comedy (was 28 Science), you do manual follow for IG
        },
        "status": {
            "privacyStatus": "private",           # required for scheduling
            "publishAt": publish_at_utc,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,  # ponytail: disclose AI per YT Mar 2024 policy - avoids "Based on available info" auto-label
        },
    }
    media = MediaFileUpload(meta["file"], chunksize=-1, resumable=True, mimetype="video/mp4")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload {int(status.progress() * 100)}%...")
    return response["id"]


def main() -> int:
    if PAUSE_FILE.exists():
        try:
            if datetime.strptime(PAUSE_FILE.read_text(encoding="utf-8").strip(),
                                 "%Y-%m-%d") >= datetime.now():
                print(f"Paused until {PAUSE_FILE.read_text().strip()} - skipping YouTube uploads.")
                return 0
        except ValueError:
            pass

    pendings = sorted(PENDING_DIR.glob("*.json")) if PENDING_DIR.exists() else []
    if not pendings:
        print("No pending videos.")
        return 0

    state = load_state()
    used = set(state["used_slots"])
    try:
        service = get_service()
    except HttpError as exc:
        print(f"Auth error: {exc}")
        return 1

    ok = fail = 0
    for p in pendings:
        meta = json.loads(p.read_text(encoding="utf-8"))
        kind = meta.get("kind", "video" if (meta.get("duration") or 61) > 60 else "short")
        if not Path(meta["file"]).exists():
            print(f"[SKIP] missing file {meta['file']}")
            p.unlink(missing_ok=True)
            continue
        try:
            slot_local = next_free_slot(kind, used)
            from datetime import timezone
            slot_iso = slot_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            vid = upload_one(service, meta, slot_iso)
            used.add(slot_local.strftime("%Y-%m-%d %H:%M"))
            state["used_slots"] = sorted(used)[-500:]
            state["uploaded"].append({
                "youtube_id": vid, "kind": kind,
                "publish_at": slot_local.strftime("%Y-%m-%d %H:%M"),
                "title": meta["title"],
                "source_url": meta["source_url"],
            })
            save_state(state)
            DONE_DIR.mkdir(parents=True, exist_ok=True)
            p.rename(DONE_DIR / p.name)   # keep for Instagram cross-posting
            ok += 1
            print(f"[OK] {kind} -> https://www.youtube.com/watch?v={vid} "
                  f"goes LIVE {slot_local.strftime('%a %Y-%m-%d %H:%M')}")
        except HttpError as exc:
            reason = ""
            try:
                reason = exc.error_details[0].get("reason", "") if exc.error_details else ""
            except Exception:
                pass
            print(f"[FAIL] {meta.get('title', '')[:50]}: {reason or exc}")
            if "quotaExceeded" in str(reason):
                print("Quota exhausted - remaining videos will be retried tomorrow.")
                break
            fail += 1

    # trim old used slots (>90 days past)
    cutoff = (datetime.now().astimezone() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M")
    state["used_slots"] = [s for s in state["used_slots"] if s >= cutoff]
    save_state(state)

    print(f"\nSummary: {ok} scheduled, {fail} failed, {len(list(PENDING_DIR.glob('*.json')))} left pending")
    upcoming = [u for u in state["uploaded"][-15:]]
    if upcoming:
        print("\nUpcoming queue:")
        for u in upcoming:
            print(f"  {u['publish_at']}  [{u['kind']}]  {u['title'][:60]}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
