"""SQLite hub DB — replaces scattered JSON files.

Tables: accounts, posts, jobs, metrics, events (event log),
agent_runs, trends_history, competitors, brand_voice.
Stdlib sqlite3, one file: hub.db. All queryable.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_FILE = BASE / "hub.db"
_lock = threading.Lock()


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init() -> None:
    with _lock, conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS accounts(
            id TEXT PRIMARY KEY, platform TEXT, name TEXT,
            description TEXT, link TEXT,
            api_creds TEXT,            -- json: tokens/ids (no passwords)
            browser_creds TEXT,        -- json: username/password (local only)
            voice TEXT,                -- json: brand voice guide
            pillars TEXT,              -- json: content pillars
            banned_topics TEXT,        -- json: banned topics list
            created_at TEXT);
        CREATE TABLE IF NOT EXISTS posts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT, account_id TEXT, title TEXT,
            description TEXT, media_type TEXT, file TEXT,
            tags TEXT, status TEXT,    -- draft|queued|posted|failed
            post_id TEXT, error TEXT,
            created_at TEXT, posted_at TEXT, scheduled_at TEXT);
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,                 -- post|comment|watch|multi
            payload TEXT,              -- json
            status TEXT,               -- pending|running|done|failed|cancelled
            result TEXT, log TEXT,
            created_at TEXT, started_at TEXT, finished_at TEXT);
        CREATE TABLE IF NOT EXISTS metrics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT, account_id TEXT, post_id TEXT,
            variant_id TEXT, experiment_id TEXT,
            followers INTEGER, following INTEGER, posts INTEGER,
            views INTEGER, likes INTEGER, comments INTEGER,
            extra TEXT, captured_at TEXT);
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT, detail TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS agent_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT, task TEXT, status TEXT, summary TEXT,
            detail TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS trends_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,               -- learn|genre|monitor
            topic TEXT, tags TEXT, counts TEXT,
            captured_at TEXT);
        CREATE TABLE IF NOT EXISTS competitors(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            handle TEXT, platform TEXT, url TEXT,
            followers INTEGER, posts INTEGER, last_seen TEXT,
            notes TEXT);
        CREATE TABLE IF NOT EXISTS inbox(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT, account_id TEXT, account_name TEXT,
            kind TEXT,                -- comment|dm|mention|follow
            from_user TEXT, text TEXT, url TEXT,
            status TEXT,              -- unread|replied|ignored
            reply TEXT, captured_at TEXT);
        """)
        # migrations for pre-existing DBs
        cols = {r[1] for r in c.execute("PRAGMA table_info(metrics)")}
        if "variant_id" not in cols:
            c.execute("ALTER TABLE metrics ADD COLUMN variant_id TEXT")
            c.execute("ALTER TABLE metrics ADD COLUMN experiment_id TEXT")
            c.execute("ALTER TABLE metrics ADD COLUMN post_id TEXT")
            c.execute("ALTER TABLE metrics ADD COLUMN views INTEGER")
            c.execute("ALTER TABLE metrics ADD COLUMN likes INTEGER")
            c.execute("ALTER TABLE metrics ADD COLUMN comments INTEGER")
        pcols = {r[1] for r in c.execute("PRAGMA table_info(posts)")}
        if "scheduled_at" not in pcols:
            c.execute("ALTER TABLE posts ADD COLUMN scheduled_at TEXT")


def save_inbox(platform: str, account_id: str, account_name: str,
               kind: str, from_user: str, text: str, url: str = "") -> None:
    """Insert an inbox item, deduping identical (from,text,url)."""
    with _lock, conn() as c:
        dup = c.execute("SELECT id FROM inbox WHERE from_user=? AND "
                          "text=? AND url=?",
                          (from_user, text, url)).fetchone()
        if dup:
            return
        c.execute("INSERT INTO inbox(platform,account_id,account_name,"
                    "kind,from_user,text,url,status,captured_at) "
                    "VALUES(?,?,?,?,?,?,?,'unread',?)",
                    (platform, account_id, account_name, kind, from_user,
                     text, url, time.strftime("%Y-%m-%d %H:%M")))


def list_inbox(status: str = "", limit: int = 100) -> list[dict]:
    with _lock, conn() as c:
        if status:
            rows = c.execute("SELECT * FROM inbox WHERE status=? ORDER BY "
                               "id DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM inbox ORDER BY id DESC LIMIT ?",
                               (limit,)).fetchall()
        return [dict(r) for r in rows]


def mark_inbox(item_id: int, status: str, reply: str = "") -> None:
    with _lock, conn() as c:
        c.execute("UPDATE inbox SET status=?, reply=? WHERE id=?",
                    (status, reply, item_id))


def log_event(kind: str, detail: str = "") -> None:
    with _lock, conn() as c:
        c.execute("INSERT INTO events(kind,detail,created_at) "
                    "VALUES(?,?,?)",
                    (kind, detail, time.strftime("%Y-%m-%d %H:%M:%S")))


def run_agent(agent: str, task: str, status: str = "done",
              summary: str = "", detail: str = "") -> int:
    with _lock, conn() as c:
        cur = c.execute("INSERT INTO agent_runs"
                          "(agent,task,status,summary,detail,created_at)"
                          " VALUES(?,?,?,?,?,?)",
                          (agent, task, status, summary, detail,
                           time.strftime("%Y-%m-%d %H:%M:%S")))
        return cur.lastrowid


def save_trend(source: str, topic: str, tags: list, counts: dict) -> None:
    with _lock, conn() as c:
        c.execute("INSERT INTO trends_history"
                    "(source,topic,tags,counts,captured_at) VALUES(?,?,?,?,?)",
                    (source, topic, json.dumps(tags),
                     json.dumps(counts), time.strftime("%Y-%m-%d %H:%M")))


def save_metric(platform: str, account_id: str, followers: int = 0,
                following: int = 0, posts: int = 0,
                extra: dict | None = None, post_id: str = "",
                variant_id: str = "", experiment_id: str = "",
                views: int = 0, likes: int = 0, comments: int = 0) -> None:
    """Time-series snapshot — every call INSERTs a new row
    (growth curves come free; never overwrites)."""
    with _lock, conn() as c:
        c.execute("INSERT INTO metrics(platform,account_id,post_id,"
                    "variant_id,experiment_id,followers,following,posts,"
                    "views,likes,comments,extra,captured_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (platform, account_id, post_id, variant_id,
                     experiment_id, followers, following, posts,
                     views, likes, comments,
                     json.dumps(extra or {}),
                     time.strftime("%Y-%m-%d %H:%M:%S")))


def create_job(kind: str, payload: dict) -> int:
    with _lock, conn() as c:
        cur = c.execute("INSERT INTO jobs(kind,payload,status,created_at) "
                          "VALUES(?,?,'pending',?)",
                          (kind, json.dumps(payload, ensure_ascii=False),
                           time.strftime("%Y-%m-%d %H:%M:%S")))
        return cur.lastrowid


def next_job() -> sqlite3.Row | None:
    with _lock, conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE status='pending' "
                          "ORDER BY id LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE jobs SET status='running', started_at=? "
                        "WHERE id=?", (time.strftime("%Y-%m-%d %H:%M:%S"),
                                       row["id"]))
        return row


def finish_job(job_id: int, status: str, result: str = "",
               log: str = "") -> None:
    with _lock, conn() as c:
        c.execute("UPDATE jobs SET status=?, result=?, log=?, finished_at=? "
                    "WHERE id=?", (status, result, log,
                                     time.strftime("%Y-%m-%d %H:%M:%S"),
                                     job_id))


def cancel_job(job_id: int) -> None:
    with _lock, conn() as c:
        c.execute("UPDATE jobs SET status='cancelled', finished_at=? "
                    "WHERE id=?",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), job_id))


def list_jobs(limit: int = 50) -> list[dict]:
    with _lock, conn() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
        return [dict(r) for r in rows]


def record_post(platform: str, account_id: str, title: str,
                description: str, media_type: str, file: str,
                tags: list, status: str = "posted",
                post_id: str = "", error: str = "",
                scheduled_at: str = "") -> int:
    with _lock, conn() as c:
        cur = c.execute(
            "INSERT INTO posts(platform,account_id,title,description,"
            "media_type,file,tags,status,post_id,error,created_at,"
            "posted_at,scheduled_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (platform, account_id, title, description, media_type, file,
             json.dumps(tags), status, post_id, error,
             time.strftime("%Y-%m-%d %H:%M"),
             time.strftime("%Y-%m-%d %H:%M") if status == "posted" else "",
             scheduled_at))
        return cur.lastrowid


def reschedule_post(post_id: int, scheduled_at: str) -> None:
    """Calendar drag-drop — the ONLY thing it does: update one row's
    scheduled_at. The scheduler stays the single source of truth."""
    with _lock, conn() as c:
        c.execute("UPDATE posts SET scheduled_at=? WHERE id=?",
                    (scheduled_at, post_id))


def list_scheduled() -> list[dict]:
    with _lock, conn() as c:
        rows = c.execute("SELECT id, platform, account_id, title, "
                           "scheduled_at, status FROM posts WHERE "
                           "scheduled_at != '' ORDER BY scheduled_at")\
            .fetchall()
        return [dict(r) for r in rows]


def list_posts(limit: int = 100) -> list[dict]:
    with _lock, conn() as c:
        rows = c.execute("SELECT * FROM posts ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
        return [dict(r) for r in rows]


# ---------------- account helpers (migrate from JSON) ----------------
def migrate_accounts_from_json() -> int:
    """One-time import of social_accounts.json into SQLite."""
    p = BASE / "social_accounts.json"
    if not p.exists():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    n = 0
    with _lock, conn() as c:
        for platform, accts in data.items():
            for a in accts:
                c.execute("INSERT OR REPLACE INTO accounts"
                            "(id,platform,name,description,link,api_creds,"
                            "browser_creds,created_at) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (a.get("_id"), platform, a.get("name"),
                             a.get("description"), a.get("link"),
                             json.dumps({k: a[k] for k in
                                         ("ig_user_id", "graph_token",
                                          "token_file", "page_id",
                                          "page_token", "bearer_token",
                                          "access_token",
                                          "organization_urn") if a.get(k)}),
                             json.dumps({k: a[k] for k in
                                         ("username", "password")
                                         if a.get(k)}),
                             time.strftime("%Y-%m-%d %H:%M")))
                n += 1
    return n


def all_accounts() -> dict:
    """Accounts grouped by platform (api_creds/browser_creds parsed)."""
    with _lock, conn() as c:
        rows = c.execute("SELECT * FROM accounts ORDER BY platform, name")\
            .fetchall()
    out: dict = {}
    for r in rows:
        a = {"_id": r["id"], "name": r["name"],
             "description": r["description"], "link": r["link"],
             "voice": json.loads(r["voice"] or "null"),
             "pillars": json.loads(r["pillars"] or "null"),
             "banned_topics": json.loads(r["banned_topics"] or "null")}
        a.update(json.loads(r["api_creds"] or "{}"))
        a.update(json.loads(r["browser_creds"] or "{}"))
        out.setdefault(r["platform"], []).append(a)
    return out


def save_account_meta(account_id: str, voice=None, pillars=None,
                      banned_topics=None) -> None:
    with _lock, conn() as c:
        if voice is not None:
            c.execute("UPDATE accounts SET voice=? WHERE id=?",
                        (json.dumps(voice, ensure_ascii=False), account_id))
        if pillars is not None:
            c.execute("UPDATE accounts SET pillars=? WHERE id=?",
                        (json.dumps(pillars, ensure_ascii=False),
                         account_id))
        if banned_topics is not None:
            c.execute("UPDATE accounts SET banned_topics=? WHERE id=?",
                        (json.dumps(banned_topics, ensure_ascii=False),
                         account_id))


init()
