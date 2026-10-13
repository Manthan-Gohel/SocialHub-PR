"""AI engine: content-aware SEO + humanized comment generation.

Hashtags/title/description are derived from the RAW input's actual
content (comedy, AI, story, food, ...), NOT hardcoded to #ai.
Uses Omniroute LLM when available; falls back to content-aware
templates so it always works even if free LLM tiers are exhausted.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
TRENDING_FILE = BASE / "trending_tags.json"
OMNIRUTE_URL = "http://localhost:20128/v1/chat/completions"

POWER_WORDS = ["Mind-Blowing", "Unbelievable", "Insane", "Shocking",
               "You Won't Believe", "Epic", "Crazy", "Incredible"]

CTA_VARIANTS = [
    "🔔 Follow for more like this!",
    "🔔 Follow — new posts every day!",
    "❤️ Like & follow for more!",
    "💾 Save this & share with a friend 👇",
    "👀 Follow for daily videos like this!",
    "🤯 More coming — stay tuned!",
]

# Category keyword → hashtag pool. Content is matched against these.
CATEGORY_KEYWORDS = {
    "comedy": ["comedy", "funny", "lol", "laugh", "joke", "humor", "meme",
                 "prank", "savage", "roast", "cringe", "skit"],
    "ai": ["ai", "artificial intelligence", "sora", "midjourney", "aigenerated",
             "aianimation", "aiart", "neural", "gpt", "robot", "machine learning"],
    "story": ["story", "storytime", "kahani", "tale", "narrative", "moral",
                "motivational", "inspiring", "lesson", "real story"],
    "baby": ["baby", "infant", "toddler", "kid", "child", "newborn", "cute baby"],
    "food": ["food", "recipe", "cooking", "chef", "yummy", "delicious", "meal",
               "street food", "foodporn", "baking", "dish"],
    "fitness": ["fitness", "workout", "gym", "exercise", "health", "muscle",
                  "fit", "yoga", "running", "training"],
    "dance": ["dance", "dancing", "choreography", "dancer", "moves"],
    "pet": ["dog", "cat", "puppy", "kitten", "pet", "animal", "cute animals",
            "parrot", "rabbit"],
    "travel": ["travel", "trip", "adventure", "wanderlust", "explore", "vacation",
                 "destination", "mountains", "beach"],
    "music": ["music", "song", "singing", "cover", "musician", "melody", "beat",
                "guitar", "piano", "rap"],
    "fashion": ["fashion", "style", "outfit", "ootd", "beauty", "makeup",
                  "clothes", "streetwear"],
    "gaming": ["gaming", "gamer", "gameplay", "videogame", "game", "esports",
                 "stream", "minecraft", "fortnite"],
    "education": ["education", "learn", "learning", "facts", "how to", "tutorial",
                    "tips", "knowledge", "science", "history", "explain"],
    "news": ["news", "breaking", "update", "headlines", "current affairs",
               "politics", "world"],
}

# Fallback high-volume general tags (content-agnostic but not all-AI)
GENERIC_VIRAL = ["viral", "trending", "explorepage", "reelsinstagram",
                   "trendingshorts", "fyp", "foryou", "reels", "viralreels",
                   "trendingnow", "foryoupage", "explore", "viralvideo"]

# Per-category engagement hook word for the title/description
CATEGORY_HOOK = {
    "comedy": "This made me laugh way too hard",
    "ai": "This was made 100% with AI",
    "story": "You need to hear this story",
    "baby": "Look at this adorable baby",
    "food": "This food is unreal",
    "fitness": "This workout is no joke",
    "dance": "These moves are insane",
    "pet": "This pet is too cute",
    "travel": "This place is breathtaking",
    "music": "This song is a banger",
    "fashion": "This style is everything",
    "gaming": "This gameplay is cracked",
    "education": "This will blow your mind",
    "news": "You need to see this",
}


def _load_trending() -> dict:
    if TRENDING_FILE.exists():
        try:
            return json.loads(TRENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def detect_categories(text: str, top_n: int = 2) -> list[str]:
    """Return the best-matching content categories for the raw text."""
    text = (text or "").lower()
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in kws if kw in text)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return [c for c, s in ranked[:top_n] if s > 0]


def build_tags(text: str, platform: str = "instagram",
               max_tags: int = 8) -> list[str]:
    """Content-aware hashtags: detected categories + trending.

    2026 best practice: 3-8 FOCUSED tags beat stuffing 30.
    Order = best tags first (category → trending → viral).
    """
    cats = detect_categories(text)
    trending_db = _load_trending()
    tags: list[str] = []

    # 1) Category-specific tags (primary category gets most slots)
    if cats:
        primary = cats[0]
        pool = list(CATEGORY_KEYWORDS.get(primary, []))
        pool = [re.sub(r"\s+", "", kw) for kw in pool]
        tags.extend(pool[:4])
        for c in cats[1:]:
            extra = [re.sub(r"\s+", "", kw)
                       for kw in CATEGORY_KEYWORDS.get(c, [])]
            tags.extend(extra[:2])

    # 2) Trending-this-week tags for the primary category (from live cache)
    if cats:
        tags.extend(trending_db.get(cats[0], [])[:3])

    # 3) Tags learned from real viral reels (reel_learner.py)
    tags.extend(trending_db.get("_learned", [])[:3])

    # 4) Trending universal tags (live, e.g. viral/reels/trending/explore)
    tags.extend(trending_db.get("_general", [])[:4])

    # 5) A couple of evergreen viral tags
    tags.extend(GENERIC_VIRAL[:2])

    # dedupe, preserve order, cap
    seen: set[str] = set()
    out = []
    for t in tags:
        t = t.lower().strip("#")
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:max_tags]


def _llm(prompt: str, max_tokens: int = 600) -> str | None:
    """Shared LLM client (NVIDIA NIM). Returns None if unavailable."""
    import llm
    return llm.chat(prompt, max_tokens=max_tokens)


def _extract_json(text: str):
    """Extract the last valid JSON object from LLM/reasoning text.

    Reasoning models echo the prompt's template JSON and keep
    reasoning after it, so greedy regexes and raw json.loads both
    fail (Extra data). Collect all balanced {...} blobs, try last
    first, and reject literal "..." placeholder values."""
    if not text:
        return None
    candidates: list[str] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    candidates.append(text[start:i + 1])
                    start = -1
    for cand in reversed(candidates):
        try:
            data = json.loads(cand)
        except Exception:
            continue
        if isinstance(data, dict):
            vals = [v for v in data.values()
                    if isinstance(v, str) and v.strip() in ("...", "")] \
                if data else []
            if data.get("title") and data.get("title") not in ("...", ""):
                return data
            # array-style or other dict without title placeholder junk
            if not vals:
                return data
    return None


def generate_seo(raw_title: str, raw_desc: str = "",
                 platform: str = "youtube",
                 seed: str = "") -> dict:
    """Return SEO title, description, tags.

    seed: different seed → different power word + CTA variant, so
    posting the same video to multiple accounts gives EACH a unique,
    video-related title/description (never identical)."""
    # Try LLM first
    llm_out = _llm(
        f"Rewrite this as a viral {platform} post. "
        f"Detect its real category (comedy/AI/story/food/etc) from the "
        f"content — do NOT assume it's AI. Title: {raw_title}\n"
        f"Description: {raw_desc}\n"
        f"Return ONLY this JSON, nothing else: "
        f'{{"title": "...", "description": "...", "tags": ["...", "..."]}} '
        f"with category-matched viral keywords and hashtags. Make the "
        f"description human and video-related.", max_tokens=800)
    if llm_out:
        data = _extract_json(llm_out)
        if isinstance(data, dict) and data.get("title"):
            return data

    # Content-aware template fallback (always works)
    combined = f"{raw_title} {raw_desc}"
    cats = detect_categories(combined)
    primary = cats[0] if cats else None

    clean = re.sub(r"#\w+", "", raw_title or "")
    clean = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" -|.,")[:80] or "Video"
    seed_hash = int(hashlib.md5((clean + seed).encode()).hexdigest(), 16)
    pw = POWER_WORDS[seed_hash % len(POWER_WORDS)]
    title = f"{pw} {clean} 🤯"

    hook = CATEGORY_HOOK.get(primary, "This is unreal")
    cta = CTA_VARIANTS[seed_hash % len(CTA_VARIANTS)]
    tags = build_tags(combined, platform)
    desc = (f"{hook} {clean}\n\n{cta}\n\n"
            f"{raw_desc}\n\n"
            + " ".join(f"#{t}" for t in tags))
    return {"title": title, "description": desc[:2200],
            "tags": tags, "trending_topics": _load_trending().get(
                "trending_topics_oct2026", [])[:3]}


# ---- Humanized comments ----
_COMMENT_TEMPLATES = [
    "{emoji} {idea} — this is actually insane {filler}",
    "wait, {idea}?? nobody showed me this before {filler}",
    "bro {idea} is the future {emoji} {filler}",
    "i literally just watched {idea} 3 times {filler}",
    "ok but why is {idea} so good?? {emoji} {filler}",
    "this {idea} just broke my brain {filler}",
    "imagine waking up to {idea} every day {emoji} {filler}",
    "the way {idea} just flows is unreal {filler}",
    "day {n}: still thinking about {idea} {filler}",
    "{idea} deserves way more views {emoji} {filler}",
]
EMOJIS = ["🤯", "🔥", "💀", "😂", "👀", "✨", "🚀", "😳", "🫠", "💯"]
FILLERS = ["fr fr", "no cap", "real talk", "deadass", "lowkey obsessed",
           "this is it", "period", "honestly??", "not me watching this at 3am",
           "instant follow", "save this", "share this", "ok this is crazy"]


def generate_comments(idea: str, count: int = 5, seed: str = "") -> list[str]:
    """Generate human-like comment variants for a raw idea."""
    llm_out = _llm(
        f"Write {count} natural, human-sounding social media comments "
        f"about this topic: {idea}\nMake them casual, varied, with emojis "
        f"and filler words like a real user. Return one comment per line, "
        f"numbered.", max_tokens=500)
    if llm_out:
        lines = [re.sub(r"^\d+[\.\)]\s*", "", ln).strip()
                 for ln in llm_out.splitlines() if ln.strip()]
        if lines:
            return lines[:count]

    rng = random.Random(int(hashlib.md5((idea + seed).encode()).hexdigest(), 16))
    out = []
    for i in range(count):
        tpl = _COMMENT_TEMPLATES[i % len(_COMMENT_TEMPLATES)]
        out.append(tpl.format(idea=idea, emoji=rng.choice(EMOJIS),
                              filler=rng.choice(FILLERS),
                              n=rng.randint(1, 9)))
    return out
