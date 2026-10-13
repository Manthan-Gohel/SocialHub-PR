"""Job runner — browser posting must NOT run inside HTTP request
handlers (they time out and block).

Persistent job table (hubdb.jobs) + one worker thread + status
polling + cancel. The dashboard enqueues jobs; the worker executes
them one at a time (browser flows are human-supervised anyway).
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import hubdb

BASE = Path(__file__).resolve().parent
_worker: threading.Thread | None = None
_stop = threading.Event()
_wake = threading.Event()


def _execute(job) -> tuple[str, str, str]:
    """Run one job by kind. Returns (status, result_json, log)."""
    kind = job["kind"]
    payload = json.loads(job["payload"] or "{}")
    log = ""

    if kind == "multi-post-seo":
        # SEO generated per account inside the job (LLM is slow —
        # fine in the background), then posts one at a time
        import ai_engine as _ai
        platform = payload.get("platform", "instagram")
        jobs = payload.get("jobs", [])
        enriched = []
        for i, j in enumerate(jobs):
            try:
                seo = _ai.generate_seo(
                    payload.get("raw_title") or "video",
                    payload.get("raw_desc", ""), platform,
                    seed=f"{j.get('username')}{i}")
            except Exception:
                seo = {"title": payload.get("raw_title") or "video",
                         "description": payload.get("raw_desc", ""),
                         "tags": []}
            enriched.append({**j,
                               "title": seo.get("title", ""),
                               "caption": seo.get("description", ""),
                               "media_type": ("reel" if
                                               payload.get("media_type")
                                               in ("reels", "shorts")
                                               else "video")})
        inner = {"platform": platform, "jobs": enriched}
        return _execute({"kind": "multi-post",
                           "payload": json.dumps(inner, ensure_ascii=False),
                           "id": job["id"]})

    if kind == "multi-post":
        path = BASE / "posts_pending.json"
        path.write_text(json.dumps(payload, ensure_ascii=False),
                          encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(BASE / "browser_poster.py"),
             "--jobs-file", str(path)], capture_output=True, text=True,
            cwd=str(BASE), timeout=3600)
        log = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-500:]
        results = []
        # parse the RESULTS json printed by browser_poster
        if "RESULTS:" in log:
            try:
                blob = log.split("RESULTS:", 1)[1].strip()
                results = json.loads(blob[:blob.rindex("]") + 1])
            except Exception:
                pass
        ok = all(r.get("ok") for r in results) if results else False
        for r in results:
            if r.get("username"):
                hubdb.record_post(payload.get("platform", "instagram"),
                                    "", r.get("title", ""), "", "multi",
                                    payload.get("jobs", [{}])[0].get("file", ""),
                                    [], status="posted" if r.get("ok")
                                    else "failed",
                                    error=r.get("error", ""))
        return ("done" if ok else "failed",
                  json.dumps({"results": results}), log)

    if kind == "multi-comment" or kind == "multi-watch":
        path = BASE / "jobs_pending.json"
        path.write_text(json.dumps(payload, ensure_ascii=False),
                          encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(BASE / "browser_commenter.py"),
             "--jobs-file", str(path)], capture_output=True, text=True,
            cwd=str(BASE), timeout=3600)
        log = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-500:]
        return "done", json.dumps({"log_tail": log[-800:]}), log

    if kind == "learn-reel":
        import reel_learner
        out = reel_learner.learn(payload.get("url", ""),
                                   payload.get("username", ""),
                                   payload.get("password", ""))
        if payload.get("save_tags") and out.get("hashtags"):
            out["saved_tags"] = reel_learner.save_learned_tags(
                out["hashtags"])
        hubdb.save_trend("learn", payload.get("url", ""),
                           out.get("hashtags", []), out.get("counts", {}))
        return "done", json.dumps(out, ensure_ascii=False), ""

    if kind == "competitor-snapshot":
        import fleet
        out = fleet.competitor_snapshot(payload.get("handle", ""),
                                          payload.get("platform",
                                                        "instagram"))
        return ("done" if out.get("ok") else "failed",
                  json.dumps(out, ensure_ascii=False), "")

    return "failed", json.dumps({"error": f"unknown job kind: {kind}"}), ""


def _worker_loop() -> None:
    while not _stop.is_set():
        if not _wake.wait(timeout=2):
            continue
        _wake.clear()
        while not _stop.is_set():
            job = hubdb.next_job()
            if not job:
                break
            hubdb.log_event("job_start", f"#{job['id']} {job['kind']}")
            try:
                status, result, log = _execute(job)
            except Exception as e:
                status, result, log = ("failed",
                                         json.dumps({"error": str(e)[:300]}),
                                         str(e)[:500])
            hubdb.finish_job(job["id"], status, result, log)
            hubdb.log_event("job_end", f"#{job['id']} {job['kind']} "
                              f"-> {status}")


def start() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_worker_loop, daemon=True)
    _worker.start()


def enqueue(kind: str, payload: dict) -> int:
    job_id = hubdb.create_job(kind, payload)
    _wake.set()
    return job_id


def stop() -> None:
    _stop.set()
    _wake.set()
