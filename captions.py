"""Generate SEO-optimized titles, descriptions, tags (YouTube) and captions (Instagram).
Deterministic per source_id so re-runs stay stable."""
from __future__ import annotations

import hashlib
import os
import re

# Optional XKIRO / Qwen API integration
_XKIRO_KEY = os.environ.get("XKIRO_API_KEY", "")
_XKIRO_CLIENT = None
if _XKIRO_KEY:
    try:
        from openai import OpenAI
        _XKIRO_CLIENT = OpenAI(base_url="https://api.xkiro.com/v1", api_key=_XKIRO_KEY)
    except Exception:
        _XKIRO_CLIENT = None

# ---------- helpers ----------
def _pick(pool: list[str], seed: str) -> str:
    return pool[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(pool)]


def clean_title(raw: str) -> str:
    import html
    t = html.unescape(raw or "")
    t = re.sub(r"#\w+", "", t)                    # strip hashtags
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)  # strip emojis
    t = re.sub(r"\s+", " ", t).strip(" -|.,")
    return t[:80].strip()


def _qwen_generate(prompt: str) -> str | None:
    """Call Qwen via xkiro API; return None if key unavailable or error."""
    if not _XKIRO_CLIENT:
        return None
    try:
        completion = _XKIRO_CLIENT.chat.completions.create(
            model="qwen/qwen3.8-max:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=120,
        )
        return completion.choices[0].message.content.strip()
    except Exception:
        return None


# ---------- YouTube ----------
from seo_optimize import browse_title, search_description  # noqa: E402

YT_HOOKS = [
    "This was created 100% with Artificial Intelligence \U0001F916",
    "AI is getting scary good at this\u2026 \U0001F440",
    "You won't believe this is made by AI \U0001F525",
    "The future of content is HERE \u26A1",
    "No camera. No editor. Just AI. \U0001F3AC",
]

# ponytail: historical hashtag tails stripped by seo_boost before regen.
# multi-word first (single words would eat them mid-match).
YT_SUFFIXES = [
    "#shorts #aibaby #ytshorts",
    "#shorts #viral #explore #aishorts",
    "#shorts #viral #trending #ai",
    "#ai #aivideo #funnyvideo #shorts",
    "#shorts #shortvideo #shortfeed",
    "#aibaby #viralbaby #funnyvideo #shorts",
    "#shorts #funny #comedy #ai",
    "#shorts #viralvideo #ai",
    "#shorts",
]


def generate_youtube(meta: dict) -> dict:
    # ponytail: seo_optimize ports deeployCO/youtube-seo-skills Tier-2 rules
    # (Browse-first emotional title 45-70c, keyword<40c, above-fold desc, 12 tags)
    title = browse_title(meta)
    desc, tags = search_description(meta)
    hook = _pick(YT_HOOKS, meta.get("source_id", "x"))
    desc = desc.replace(
        "New AI videos daily - subscribe for more.",
        f"{hook}\nNew AI videos daily - subscribe for more.",
    )
    return {"title": title, "description": desc[:5000], "tags": tags}


# ---------- Instagram ----------
from ig_seo import ig_caption  # noqa: E402

COPYRIGHT_IG = (
    "⚠️ Copyright Disclaimer: No copyright infringement intended. All rights belong "
    "to the respective owners. For credit or removal, please DM us."
)


def generate_instagram(meta: dict) -> str:
    # ponytail: ig_seo ports pavelhov MATCH framework (keyword-first caption,
    # 3-5 labels, sends CTA). Old 22-hashtag captions were the 0-view problem.
    cap = ig_caption(meta)
    return cap + "\n" + COPYRIGHT_IG
