"""Instagram keyword-search caption generator, ported from pavelhov/social-media-skills
instagram-seo (MATCH framework) + instagram-growth (2026 reality).

Key changes vs old captions.generate_instagram:
- Primary keyword in FIRST sentence / ~125 chars (IG search = semantic -> metadata -> CV)
- 3-5 topic-label hashtags max (hashtags deprioritized since late 2024; 22 = stuffing)
- Caption matches the visual (names the actual subject, not generic "AI took over")
- CTA engineered for sends (DM shares ~3-5x more valuable than likes)
"""
from __future__ import annotations

import hashlib
import re

# keyword clusters per niche: primary first, 3-5 total
IG_CLUSTERS = {
    "baby": ["funny AI baby videos", "AI baby comedy", "cute AI baby"],
    "football": ["funny AI football videos", "AI football parody", "AI Haaland"],
    "snake": ["funny AI animal videos", "AI animals comedy"],
    "story": ["AI story video", "AI Hindi kahani", "AI animated story"],
    "car": ["AI car videos", "futuristic AI vehicles"],
    "goku": ["AI anime video", "AI Goku animation"],
    "cooking": ["AI cooking video", "AI ASMR food"],
    "ai": ["funny AI videos", "AI generated video", "AI comedy"],
}

# topic-label hashtags (3-5 max, niche-matched, no #fyp/#explorepage spam).
# ponytail: merged live 50-video pull 2026-09-23 winners; #ai always first.
IG_LABELS = {
    "baby": ["#ai", "#aibaby", "#funnybaby", "#cutebaby", "#babylaughs"],
    "football": ["#ai", "#aifootball", "#footballfunny", "#haaland"],
    "snake": ["#ai", "#aianimals", "#funnyai", "#animalcomedy"],
    "story": ["#ai", "#aistory", "#aianimation", "#hindikahani"],
    "car": ["#ai", "#aicars", "#futuristic", "#carvideos"],
    "goku": ["#ai", "#aianime", "#goku", "#dbz"],
    "cooking": ["#ai", "#aicooking", "#asmrfood", "#satisfyingvideo",
                "#oddlysatisfying"],
    "ai": ["#ai", "#aivideo", "#funnyvideo", "#viralshorts", "#aishorts"],
}

from seo_optimize import _detect_niche, _topic_words  # noqa: E402

SEND_CTAS = [
    "Send this to someone who needs a laugh today",
    "Share this with a friend who loves AI videos",
    "Tag your friend who would do exactly this",
    "DM this to your group chat right now",
]


def _pick(pool: list[str], seed: str) -> str:
    return pool[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(pool)]


def ig_caption(meta: dict) -> str:
    sid = meta.get("source_id", "x")
    raw = meta.get("title", "")
    niche = _detect_niche(raw)
    cluster = IG_CLUSTERS.get(niche, IG_CLUSTERS["ai"])
    primary = cluster[0]
    words = _topic_words(raw)
    subject = " ".join(words[:3]).lower() if words else cluster[0].lower()

    cta = _pick(SEND_CTAS, sid)
    # first sentence leads with primary keyword (search-first caption)
    first = f"{primary} - wait for the ending of this {subject}!"
    mid = (
        f"\n\n{cta} \U0001F4E4\n\n"
        f"New AI videos every day - follow for the next one.\n"
    )
    credit = ""
    if meta.get("source_url"):
        credit = f"\nOriginal (Creative Commons): {meta['source_url']}\n"
    labels = " ".join(IG_LABELS.get(niche, IG_LABELS["ai"]))
    caption = f"{first}{mid}{credit}\n{labels}"
    return caption[:2200]


def demo() -> None:
    tests = [
        {"source_id": "t1", "title": "AI baby comedy #shorts"},
        {"source_id": "t2", "title": "Haaland Genius Plan to Steal a Drink! #haaland"},
        {"source_id": "t3", "title": "\u092c\u091a\u094d\u091a\u0940 \u0915\u094b \u092c\u0938 \u092e\u0947\u0902 Kahani #ai"},
        {"source_id": "t4", "title": "random clip with no niche words"},
    ]
    for m in tests:
        c = ig_caption(m)
        first125 = c[:125].lower()
        # keyword-first check: caption must open with a cluster keyword
        assert any(first125.startswith(k.lower()) for k in
                   sum(IG_CLUSTERS.values(), [])), c[:60]
        # 3-5 labels check
        n_labels = len(re.findall(r"#\w+", c))
        assert 3 <= n_labels <= 5, f"{n_labels} labels: {c}"
        assert "#fyp" not in c and "#explorepage" not in c
        print(f"OK {m['source_id']}: {c[:70]!r} ({n_labels} labels)")


if __name__ == "__main__":
    demo()
