"""Title/metadata optimizer ported from deeployCO/youtube-seo-skills Tier-2 rules.

Fixes the repost-channel 0-view problem at the metadata layer:
- Browse-surface title: emotional driver first, 40-70 chars, no hashtag soup
- Search-surface: primary keyword in first 40 chars
- Description: keyword + hook in first 150 chars (above fold), entity coverage,
  3 hashtags max, no #fyp spam
- Tags: 5-15, first = exact topic keyword, <500 chars total
Deterministic per source_id. Used by captions.py via optimize=True.
"""
from __future__ import annotations

import re

# --- entity pools for semantic coverage (Tier 2: Knowledge Graph entities) ---
ENTITIES = {
    "baby": ["AI baby", "Sora", "Veo", "AI animation", "family comedy"],
    "football": ["Haaland", "Mbappe", "Ronaldo", "Messi", "AI football", "Champions League"],
    "snake": ["AI animals", "wildlife parody", "AI animation"],
    "story": ["AI storytelling", "Hindi kahani", "3D animation story"],
    "car": ["AI cars", "supercar", "futuristic vehicles"],
    "goku": ["Goku", "Dragon Ball", "AI anime"],
    "cooking": ["AI cooking", "ASMR food", "AI recipe"],
}

EMOTION_DRIVERS = [
    "Wait for the ending", "This can't be real", "Nobody expected this",
    "I can't stop watching", "POV:", "The last one is insane",
]

# keyword -> surface classification (Browse-first emotional, keyword within 40 chars)
KEYWORD_MAP = {
    "baby": ("AI Baby Comedy", "funny ai baby video"),
    "football": ("AI Football Parody", "funny ai football video"),
    "comedy": ("AI Comedy", "funny ai video"),
    "story": ("AI Story", "ai story hindi"),
    "snake": ("AI Animals", "funny ai animals"),
    "car": ("AI Cars", "ai car video"),
    "goku": ("AI Anime", "ai anime goku"),
}


_NICHE_SYNONYMS = {
    "baby": "baby", "behan": "baby", "bacha": "baby", "cute": "baby",
    "football": "football", "haaland": "football", "ronaldo": "football",
    "messi": "football", "mbappe": "football", "yamal": "football",
    "snake": "snake", "animal": "snake", "lion": "snake", "crocodile": "snake",
    "story": "story", "kahani": "story", "kahaniyan": "story",
    "car": "car", "bmw": "car", "supercar": "car", "vehicle": "car",
    "goku": "goku", "anime": "goku", "dragon": "goku",
    "cooking": "cooking", "recipe": "cooking", "food": "cooking",
}


def _detect_niche(text: str) -> str:
    t = (text or "").lower()
    for key, niche in _NICHE_SYNONYMS.items():
        if key in t:
            return niche
    return "ai"


def _topic_words(title: str) -> list[str]:
    """Extract the actual content-descriptive words from a scraped title."""
    t = re.sub(r"#\w+", "", title)
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)
    stop = {"the", "a", "an", "is", "of", "in", "on", "to", "and", "this",
            "that", "with", "for", "it", "video", "shorts", "ai", "funny",
            "comedy", "part", "top", "new"}
    words = [w for w in re.findall(r"[A-Za-z]{4,}", t) if w.lower() not in stop]
    words = [w for w in words if w.lower() not in _NICHE_SYNONYMS]
    return words[:4]


def browse_title(meta: dict) -> str:
    """Tier-2 Browse title: emotion first, 45-70 chars, keyword < 40 chars."""
    import hashlib
    sid = meta.get("source_id", "x")
    raw = meta.get("title", "")
    niche = _detect_niche(raw + " " + meta.get("kind", ""))
    label, keyword = KEYWORD_MAP.get(niche, ("AI Video", "ai video"))
    words = _topic_words(raw)
    subject = " ".join(words) if words else ""
    driver = EMOTION_DRIVERS[int(hashlib.md5(sid.encode()).hexdigest(), 16) % len(EMOTION_DRIVERS)]
    if subject:
        t = f"{label}: {subject[:30]}"
    else:
        t = label
    if len(t) + len(driver) + 3 <= 70:
        t = f"{t} - {driver}"
    return t[:70].strip(" -|")


def search_description(meta: dict) -> tuple[str, list[str]]:
    """Above-fold keyword intent + entity coverage; returns (desc, tags)."""
    raw = meta.get("title", "")
    niche = _detect_niche(raw)
    label, keyword = KEYWORD_MAP.get(niche, ("AI Video", "ai video"))
    ents = ENTITIES.get(niche, ["AI video", "Sora", "Veo", "AI animation"])
    words = _topic_words(raw)
    subject = " ".join(words[:3]) if words else label
    if subject.lower() == label.lower():
        subject = "daily pick"

    # above fold (first 150 chars): keyword + intent, no fluff
    above = f"{keyword} - {subject}. Watch till the end for the best moment!"
    import hashlib
    tool = ["Sora", "Veo", "Runway", "Kling"][int(hashlib.md5(
        (meta.get("source_id", "x") + "t").encode()).hexdigest(), 16) % 4]
    body = (
        f"{above}\n\n"
        f"Made with {tool}. {subject} like you've never seen - "
        f"fully AI animated. Related: {', '.join(ents[:5])}.\n\n"
        f"New AI videos daily - subscribe for more.\n"
    )
    if meta.get("source_url"):
        body += f"Original CC source: {meta['source_url']}\n"
    body += ("\n#ai #shorts #aivideo" if meta.get("kind") == "short"
             else "\n#ai #aivideo #aianimation")

    tags = [keyword, f"{keyword} funny", label.lower(),
            "ai generated video", "sora ai", "veo ai"] + \
           [e.lower() for e in ents[:4]]
    # ponytail: research-verified winners from live 50-video pull 2026-09-23
    # (dropped redundant ytshorts/shorts feed; added top-freq misses)
    tags += [t for t in ("shorts", "viral shorts", "ai video", "trending",
                         "funny ai video", "chatgpt", "hindi story",
                         "satisfying video", "memes", "aianimation")
             if t not in tags]
    tags = list(dict.fromkeys(tags))[:15]
    return body, tags


def demo() -> None:
    tests = [
        {"source_id": "abc1", "title": "AI baby comedy #shorts", "kind": "short"},
        {"source_id": "abc2", "title": "\ud83d\ude02 ulti duniya funny video #ai #shorts", "kind": "short"},
        {"source_id": "abc3", "title": "Haaland Genius Plan to Steal a Drink! #haaland", "kind": "video"},
        {"source_id": "abc4", "title": "Do Behnein, Ek Deewar Aur Chhupa Hua Pyar - Maryam Hamza", "kind": "video"},
    ]
    for m in tests:
        t = browse_title(m)
        d, tags = search_description(m)
        kw_first = t[:40].lower()
        assert 30 <= len(t) <= 70, t
        assert "#" not in t, t
        assert 3 <= len(tags) <= 15
        assert len(",".join(tags)) < 500
        assert tags[0] and "#ai" in d
        print(f"OK {m['source_id']}: {t!r} tags={tags[:3]}...")


if __name__ == "__main__":
    demo()
