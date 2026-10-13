"""Company — CEO + co-workers agent structure that works like a
real company for social media / PR.

CEO:        receives a goal, breaks it into work items, delegates to
            co-workers, collects their reports, makes the final call.
Co-workers: Analyst, Research, Content Writer, Media Handler,
            Community Manager — each does real work (live data +
            generators), never stubs.

Run via dashboard: PR Team tab -> Run Company, or:
  .venv\\Scripts\\python.exe company.py --goal "grow Celebrity Gossip"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pr_team as pr      # noqa: E402
import ai_engine as ai    # noqa: E402


# ---------------- Co-workers ----------------
def worker_analyst(goal: str, accounts: dict) -> dict:
    """Analyst: real numbers across all platforms. READ-ONLY role."""
    snap = pr.analytics_snapshot(accounts)
    working = [p for p in snap.get("platforms", []) if p.get("ok")]
    summary = f"{len(working)} platform(s) reporting live stats."
    return {"worker": "Analyst 📊", "task": "Gather real analytics",
            "permissions": "read-only (no posting, no publishing)",
            "summary": summary, "data": snap}


def worker_research(goal: str, accounts: dict) -> dict:
    """Research: mentions + sentiment + communities."""
    monitoring = pr.monitor_mentions(goal)
    communities = pr.find_communities(goal)
    sentiment_label = "unknown"
    if monitoring.get("ok"):
        summary = monitoring["summary"]
        # sentiment from the summary line
        if "negative" in summary and "positive, 0" not in summary:
            sentiment_label = "mixed/negative"
        else:
            sentiment_label = "positive/neutral"
    else:
        summary = monitoring.get("error", "no data")
    return {"worker": "Research 🔍", "task": "Monitor mentions + "
            "sentiment + communities",
            "summary": summary, "sentiment": sentiment_label,
            "data": {"monitoring": monitoring, "communities": communities}}


def worker_content_writer(goal: str, accounts: dict) -> dict:
    """Content Writer: content calendar + sample posts (unique SEO)."""
    seo_ig = ai.generate_seo(goal, platform="instagram", seed="ceo")
    seo_yt = ai.generate_seo(goal, platform="youtube", seed="ceo")
    calendar = [
        {"day": "Mon", "instagram": f"Reel: {seo_ig['title'][:40]}",
         "youtube": f"Short: {seo_yt['title'][:40]}"},
        {"day": "Wed", "instagram": "Reel: behind-the-scenes / story",
         "youtube": "Long-form: deep dive"},
        {"day": "Fri", "instagram": f"Reel: {goal[:40]} highlight",
         "youtube": f"Short: {goal[:40]} cut"},
        {"day": "Sun", "instagram": "Story: community Q&A + poll",
         "youtube": "Short: best-of-the-week"},
    ]
    return {"worker": "Content Writer ✍️",
            "task": "Weekly content calendar + sample posts",
            "summary": f"4-day calendar ready; IG + YT sample posts "
            f"generated for '{goal[:40]}'",
            "data": {"calendar": calendar, "instagram": seo_ig,
                     "youtube": seo_yt}}


def worker_media_handler(goal: str, accounts: dict) -> dict:
    """Media Handler: crisis readiness + press kit. DRAFT-ONLY role."""
    crisis = pr.crisis_plan(goal)
    return {"worker": "Media Handler 🚨",
            "task": "Crisis readiness + press kit",
            "permissions": "draft-only (can draft but NEVER publish "
                           "without human approval)",
            "summary": "5-phase crisis plan + press release + sample "
            "response posts ready",
            "data": crisis}


def worker_community(goal: str, accounts: dict) -> dict:
    """Community Manager: where to engage."""
    communities = pr.find_communities(goal)
    targets = [c["community"] for c in communities.get("communities", [])
               if c.get("threads")]
    return {"worker": "Community Manager 🤝",
            "task": "Find communities to engage",
            "summary": (f"{len(targets)} active communities found: "
                        f"{', '.join(targets[:6])}" if targets
                        else "No active communities — engage via "
                             "own channels first"),
            "data": communities}


WORKERS = [worker_analyst, worker_research, worker_content_writer,
           worker_media_handler, worker_community]


# ---------------- CEO ----------------
def ceo_run(goal: str, accounts: dict) -> dict:
    """CEO: break the goal into work items, delegate, collect
    reports, make the final call."""
    goal = (goal or "").strip() or "grow our social presence"
    reports = []
    for w in WORKERS:
        try:
            reports.append(w(goal, accounts))
        except Exception as e:
            reports.append({"worker": getattr(w, "__name__", "worker"),
                              "task": "delegated", "summary":
                              f"failed: {str(e)[:120]}", "data": {}})

    # CEO synthesizes a decision from the worker reports
    research = next((r for r in reports if r["worker"].startswith(
        "Research")), {})
    analyst = next((r for r in reports if r["worker"].startswith(
        "Analyst")), {})
    sentiment = research.get("sentiment", "unknown")
    platforms_ok = len(analyst.get("data", {}).get("platforms", [])
                       and [p for p in
                            analyst["data"]["platforms"] if p.get("ok")]
                       or [])

    actions = [
        "1. Post the Content Writer's calendar starting today "
        "(use Multi-Post for unique title/desc per account)",
        "2. Engage in the Research-found communities (browser, "
        "human-supervised, sparse)",
        "3. Run Learn on the top competitor reel; save its hashtags",
        "4. Re-run Analytics in 7 days to measure growth",
    ]
    if sentiment == "mixed/negative":
        actions.insert(0, "0. Sentiment is NEGATIVE — run the Media "
                          "Handler's crisis plan BEFORE posting promo")

    decision = (f"GOAL: {goal}\n"
                f"Sentiment: {sentiment}. {platforms_ok} platform(s) "
                f"live.\n"
                f"CEO call: execute the plan below — content first, "
                f"community second, measure after 7 days.")
    # LLM upgrade: CEO decision synthesized by the STRONG model
    try:
        llm = ai._llm(
            f"You are the CEO of a social media PR company. Goal: {goal}. "
            f"Worker reports:\n" + "\n".join(
                f"- {r.get('worker')}: {r.get('summary')}"
                for r in reports) +
            f"\nWrite a short decisive CEO call (3-4 sentences) and "
            f"3 next actions. Be concrete.", max_tokens=600, tier="strong")
        if llm:
            decision = f"GOAL: {goal}\n\n{llm}"
    except Exception:
        pass
    # Grounding: cite live sources where they exist; CEO can draft but
    # publishing stays human-approved (guardrail)
    grounded_sources = []
    research = next((r for r in reports if r["worker"].startswith(
        "Research")), {})
    mon = research.get("data", {}).get("monitoring", {})
    for m in (mon.get("mentions") or [])[:5]:
        grounded_sources.append({"source": m.get("source"),
                                   "title": m.get("title"),
                                   "url": m.get("url")})
    # log the run (stateful company memory)
    import hubdb
    run_id = hubdb.run_agent("CEO", goal, summary=decision[:200],
                               detail=json.dumps(
                                   {"action_items": actions,
                                    "sentiment": sentiment},
                                   ensure_ascii=False)[:2000])
    hubdb.log_event("company_run", f"goal='{goal[:60]}' run#{run_id}")
    return {"ok": True, "ceo": "🎯 CEO",
            "goal": goal, "decision": decision,
            "action_items": actions,
            "grounded_sources": grounded_sources,
            "publish_policy": "CEO drafts and plans; every post is "
                              "human-approved before it goes out",
            "workers_reports": reports}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    args = ap.parse_args()
    accounts = json.loads(
        (BASE / "social_accounts.json").read_text(encoding="utf-8"))
    out = ceo_run(args.goal, accounts)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
