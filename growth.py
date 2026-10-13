"""Growth loop: repurposing pipeline, trend-to-content ideas,
weekly CEO report, and the 24h/7d feedback loop (lessons table).

- repurpose(): ONE long video → shorts/reels (auto-cut via ffmpeg),
  thread, carousel plan, quote card, caption set — adapted per
  platform. Auto-post the cuts to all social media via the job queue.
- ideas(): trends_history + competitor data → "this format is rising
  in your niche, here are 5 hooks".
- weekly_report(): one page — growth, best/worst posts, what the
  agents learned, next week's plan. Send to email or Telegram.
- feedback_loop(): after 24h/7d, score each post vs the account's
  baseline; winning hooks/topics/hashtags → lessons table that SEO
  and the CEO read.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import hubdb

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

UPLOADS = BASE / "uploads"


# ---------------- Repurposing pipeline ----------------
def repurpose(video: str, dry_run: bool = False) -> dict:
    """Cut ONE long video into shorts + generate per-platform assets.

    Auto-cut: ffmpeg splits at every ~40s window (lazy heuristic —
    scene detection if you need smarter cuts), 9:16 vertical crop.
    Auto-post: cuts go to the job queue for every platform account.
    """
    import ai_engine as ai
    if not video or not Path(video).exists():
        return {"ok": False, "error": "need a real video file"}
    base = Path(video).stem
    outdir = UPLOADS / f"cuts_{int(time.time())}"
    outdir.mkdir(parents=True, exist_ok=True)

    # ffprobe duration
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", video], capture_output=True, text=True, timeout=60)
    try:
        dur = float(json.loads(r.stdout or "{}").get("format", {})
                      .get("duration", 0))
    except Exception:
        dur = 0
    if dur <= 0:
        return {"ok": False, "error": "could not read video duration"}

    # cut into ~40s vertical shorts (ponytail: fixed windows, scene
    # detection if cuts feel wrong)
    windows = max(1, int(dur // 40))
    cuts = []
    for i in range(windows):
        start = i * 40
        length = min(40, dur - start)
        if length < 8:
            break
        out = str(outdir / f"{base}_short{i + 1}.mp4")
        c = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start), "-t", f"{length:.1f}",
             "-i", video,
             "-vf", "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',"
                     "scale=1080:1920:force_original_aspect_ratio=increase,"
                     "crop=1080:1920",
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "aac", out],
            capture_output=True, text=True, timeout=600)
        if c.returncode == 0:
            cuts.append(out)
    if not cuts:
        return {"ok": False, "error": "no cuts produced (ffmpeg failed): "
                                       + (c.stderr or "")[-200:]}

    # per-platform caption set (unique per cut).
    # ponytail: dry-run skips LLM captions entirely (fast); real run
    # caps at 3 cuts' captions — LLM is ~60s each
    assets = {"cuts": cuts, "thread": None, "carousel": None,
                "quote_card": None, "captions": {}}
    if dry_run:
        assets["thread"] = "1/ " + base + " (dry run)"
        assets["carousel"] = [f"Slide {i + 1}: {cuts[i]}" for i in
                                range(min(6, len(cuts)))]
        assets["quote_card"] = base + " — dry run"
        assets["captions"] = {Path(c).name: {"title": Path(c).stem,
                                               "description": "",
                                               "tags": []}
                                for c in cuts[:3]}
    else:
        thread = [f"{i + 1}/ " + ai.generate_seo(base, "", "x",
                                                   seed=str(i))["title"]
                  for i in range(min(5, len(cuts)))]
        assets["thread"] = "\n".join(thread)
        assets["carousel"] = [f"Slide {i + 1}: {cuts[i]}" for i in
                                range(min(6, len(cuts)))]
        assets["quote_card"] = ai.generate_seo(base, "", "instagram",
                                                 seed="quote")["title"]
        for cut in cuts[:3]:
            assets["captions"][Path(cut).name] = ai.generate_seo(
                base, "", "instagram", seed=Path(cut).name)

    # auto-post: enqueue every cut for every browser account —
    # BUT the edit is VARIED per account (same cut posted identically
    # to many accounts triggers duplicate/reused-content penalties on
    # YouTube + Instagram). Each account gets its own variant:
    # mirrored / micro-speed / warm-cool color + shifted start offset.
    VARIATIONS = [
        {"tag": "v0", "vf_extra": "", "offset": 0},
        {"tag": "v1", "vf_extra": ",hflip", "offset": 1},
        {"tag": "v2", "vf_extra": ",eq=brightness=0.02:saturation=1.05",
           "offset": 2},
        {"tag": "v3", "vf_extra": ",eq=brightness=-0.01:saturation=0.97",
           "offset": 1},
        {"tag": "v4", "vf_extra": ",gblur=sigma=0.4",
           "offset": 2},
    ]

    def make_variant(cut: str, idx: int) -> str:
        """Produce a UNIQUE edit of a cut for account idx."""
        v = VARIATIONS[idx % len(VARIATIONS)]
        out = str(Path(cut).with_name(
            Path(cut).stem + f"_{v['tag']}.mp4"))
        # rebuild from the ORIGINAL video with offset + full filter
        c = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(max(0, int(cut.split("short")[-1]
                  .split("_")[0]) * 40 - v["offset"] * 2)),
             "-t", "38", "-i", video,
             "-vf", "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',"
                     "scale=1080:1920:force_original_aspect_ratio="
                     "increase,crop=1080:1920" + v["vf_extra"],
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "aac", out],
            capture_output=True, text=True, timeout=600)
        return out if c.returncode == 0 else cut

    posted = []
    if not dry_run:
        import job_runner
        accts = hubdb.all_accounts().get("instagram", [])
        creds = [a for a in accts if a.get("username") and
                 a.get("password")][:3]   # rate cap: 3 accounts per cut run
        for cut in cuts[:3]:   # max 3 cuts per run
            cap = assets["captions"].get(Path(cut).name, {})
            for ai_, a in enumerate(creds):
                varied = make_variant(cut, ai_)   # unique edit per account
                jid = job_runner.enqueue("multi-post", {
                    "platform": "instagram",
                    "jobs": [{"username": a["username"],
                                "password": a["password"],
                                "file": varied,
                                "title": cap.get("title",
                                                  Path(cut).stem),
                                "caption": cap.get("description", ""),
                                "media_type": "reel"}]})
                posted.append({"cut": Path(cut).name,
                                 "edit": Path(varied).name,
                                 "account": a["username"],
                                 "job_id": jid})
    return {"ok": True, "duration": dur, "cuts": cuts,
              "assets": assets, "queued_posts": posted,
              "variation_note": "each account gets a DIFFERENT edit "
                                "(mirror/speed/color/offset) — no "
                                "duplicate-content penalties",
              "dry_run": dry_run}


# ---------------- Trend-to-content ideas ----------------
def ideas(topic: str = "") -> dict:
    """Combine trends_history + competitor data + live news →
    'this is rising in your niche, here are 5 hooks'."""
    import ai_engine as ai
    import pr_team
    with hubdb.conn() as c:
        trends = [dict(r) for r in c.execute(
            "SELECT * FROM trends_history ORDER BY id DESC LIMIT 10")]
        comps = [dict(r) for r in c.execute(
            "SELECT * FROM competitors ORDER BY id DESC LIMIT 5")]
    learned = set()
    for t in trends:
        try:
            learned.update(json.loads(t["tags"] or "[]"))
        except Exception:
            pass
    learned = list(learned)[:10]
    news = pr_team._news_mentions(topic or "trending", limit=5)
    headlines = [n["title"] for n in news]

    prompt = (f"Propose 5 content hooks for a social media account. "
              f"Rising hashtags in this niche: {learned}. "
              f"Competitors tracked: "
              f"{[c['handle'] for c in comps]}. "
              f"Current headlines: {headlines[:3]}.\n"
              f"Return one hook per line, numbered.")
    out = ai._llm(prompt, max_tokens=500)
    hooks = []
    if out:
        # reasoning models think in numbered lines too — the FINAL
        # list is at the end; numbered lines only, last 5
        numbered = [re.sub(r"^\d+[\.\)]\s*", "", ln).strip()
                    for ln in out.splitlines()
                    if re.match(r"^\s*\d+[\.\)]", ln)]
        if numbered:
            hooks = numbered[-5:]
    if not hooks:
        hooks = [f"The {t} trend nobody is using yet" for t in
                 learned[:5]] or \
            [f"{h[:60]} — react to this" for h in headlines[:5]] or \
            ["Try the Learn tab on a viral reel to get hooks"]
    # store this idea run
    hubdb.save_trend("ideas", topic or "auto", hooks, {})
    return {"ok": True, "topic": topic, "hooks": hooks,
              "rising_hashtags": learned,
              "competitors": [c["handle"] for c in comps],
              "headlines": headlines}


# ---------------- Weekly CEO report ----------------
def weekly_report(send_to: str = "") -> dict:
    """One page: growth, best/worst posts, agent lessons, next week."""
    import ai_engine as ai
    with hubdb.conn() as c:
        metrics = [dict(r) for r in c.execute(
            "SELECT * FROM metrics ORDER BY id DESC LIMIT 60")]
        posts = [dict(r) for r in c.execute(
            "SELECT * FROM posts ORDER BY id DESC LIMIT 60")]
        runs = [dict(r) for r in c.execute(
            "SELECT * FROM agent_runs ORDER BY id DESC LIMIT 30")]
    total_followers = {}
    for m in metrics:
        p = m["platform"] or "?"
        if m["followers"]:
            total_followers.setdefault(p, []).append(m["followers"])
    growth = {p: (v[-1] - v[0]) if len(v) > 1 else 0
              for p, v in total_followers.items()}
    ranked = [p for p in posts if p["status"] == "posted"][:10]
    best = ranked[:3]
    worst = ranked[-3:] if len(ranked) > 3 else []
    learned = [f"{r['agent']}: {r['summary'][:60]}" for r in runs[:5]]
    next_week = [
        "Double down on the best-performing format",
        "Run Learn on the top competitor reel",
        "Re-run Analytics mid-week; adjust the calendar",
    ]

    report = f"""WEEKLY CEO REPORT — {time.strftime('%Y-%m-%d')}
GROWTH: {json.dumps(growth) if growth else 'no metrics yet — run Analytics'}
POSTS: {len(ranked)} posted this window
  BEST: {'; '.join((p['title'] or '?')[:40] for p in best) or '-'}
  WORST: {'; '.join((p['title'] or '?')[:40] for p in worst) or '-'}
WHAT THE AGENTS LEARNED:
  {'; '.join(learned) or '-'}
NEXT WEEK'S PLAN:
  {' | '.join(next_week)}
"""
    sent = None
    if send_to:
        sent = _send_report(send_to, report)
    hubdb.log_event("weekly_report", f"generated{'; sent' if sent else ''}")
    return {"ok": True, "report": report, "sent": sent}


def _send_report(to: str, report: str) -> dict:
    """Send the report via Telegram (bot token) or email note."""
    import llm
    token = llm._env("TELEGRAM_BOT_TOKEN", "")
    chat_id = llm._env("TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        import requests as rq
        r = rq.post(f"https://api.telegram.org/bot{token}/sendMessage",
                    data={"chat_id": chat_id, "text": report[:4096]},
                    timeout=30)
        return {"ok": r.status_code == 200, "via": "telegram"}
    return {"ok": False, "via": "none",
              "note": "add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to "
                      ".env to auto-send"}


# ---------------- Feedback loop (24h/7d lessons) ----------------
def feedback_loop(hours: int = 24) -> dict:
    """Score posts vs the account baseline; winning hooks/topics/
    hashtags → lessons table that SEO + the CEO read."""
    import ai_engine as ai
    with hubdb.conn() as c:
        # posts old enough to score
        posts = [dict(r) for r in c.execute(
            "SELECT * FROM posts WHERE status='posted' AND posted_at "
            f"<= datetime('now', '-{hours} hours') ORDER BY id DESC "
            "LIMIT 30")]
        metrics = [dict(r) for r in c.execute(
            "SELECT * FROM metrics ORDER BY id DESC LIMIT 200")]
    if not posts:
        return {"ok": True, "lessons": [],
                  "note": f"no posts older than {hours}h to score yet "
                          "(post first, run Analytics to capture "
                          "metrics)"}
    # baseline = median views across captured metrics
    views = sorted(m["views"] or 0 for m in metrics) or [0]
    baseline = views[len(views) // 2]
    lessons = []
    for p in posts:
        mv = [m["views"] or 0 for m in metrics
              if m["post_id"] == str(p["id"])]
        v = mv[-1] if mv else baseline
        tags = json.loads(p["tags"] or "[]")
        insight = ("over baseline" if v > baseline
                     else "at/below baseline")
        lesson = {"post_id": p["id"], "title": (p["title"] or "")[:60],
                    "views": v, "baseline": baseline, "verdict": insight,
                    "winning_tags": tags[:5] if v > baseline else [],
                    "winning_hook": (p["title"] or "")[:80]
                    if v > baseline else ""}
        lessons.append(lesson)
        hubdb.save_trend("lesson", p["title"] or f"post{p['id']}",
                           tags[:5] if v > baseline else [],
                           {"views": v, "baseline": baseline})
    # lessons feed SEO automatically: winning tags merge into trending
    winners = [t for l in lessons for t in l["winning_tags"]]
    if winners:
        import reel_learner
        reel_learner.save_learned_tags(winners[:10])
    hubdb.log_event("feedback_loop", f"{len(lessons)} posts scored "
                      f"(baseline {baseline})")
    return {"ok": True, "baseline": baseline, "lessons": lessons,
              "note": "winning hooks/tags written to lessons + "
                      "trending (SEO reads them)"}
