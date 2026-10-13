"""Shared LLM client — NVIDIA NIM (OpenAI-compatible, z-ai/glm-5.3-flash).

All AI features read this one place: SEO, humanized comments,
CEO decisions, task parsing, arena judging.
Config in .env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
"""
from __future__ import annotations

from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent


def _env(key: str, default: str | None = None) -> str | None:
    p = BASE / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return default


BASE_URL = _env("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
API_KEY = _env("LLM_API_KEY", "")
# Two-tier: FAST model for SEO/classification/comments (high volume),
# STRONG model for CEO decisions/strategy (quality matters).
MODEL_FAST = _env("LLM_MODEL_FAST", "z-ai/glm-5.3-flash")
MODEL_STRONG = _env("LLM_MODEL_STRONG", _env("LLM_MODEL",
                                                  "z-ai/glm-5.3-flash"))
# Groq: Whisper transcription + free LLM fallback
GROQ_API_KEY = _env("GROQ_API_KEY", "")
GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-120b"


def transcribe(file: str) -> dict:
    """Whisper transcription via Groq (free tier). Extracts audio
    with ffmpeg first (16kHz mono; compresses if over 25MB)."""
    import subprocess
    if not GROQ_API_KEY:
        return {"ok": False, "error": "no GROQ_API_KEY in .env"}
    wav = str(Path(file).with_suffix(".tmp.wav"))
    try:
        subprocess.run(["ffmpeg", "-y", "-i", file, "-ar", "16000",
                          "-ac", "1", wav], capture_output=True,
                          timeout=600)
        audio = wav
        if Path(wav).exists() and Path(wav).stat().st_size > 24_000_000:
            mp3 = str(Path(file).with_suffix(".tmp.mp3"))
            subprocess.run(["ffmpeg", "-y", "-i", wav, "-b:a", "64k",
                              mp3], capture_output=True, timeout=600)
            audio = mp3
        if not Path(audio).exists():
            return {"ok": False, "error": "audio extraction failed"}
        with open(audio, "rb") as f:
            r = requests.post(
                f"{GROQ_BASE}/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": f, "model": (None, "whisper-large-v3")},
                timeout=600)
        if r.status_code != 200:
            return {"ok": False,
                      "error": f"groq {r.status_code}: {r.text[:150]}"}
        return {"ok": True, "text": r.json().get("text", "")[:5000]}
    finally:
        for p in (wav, str(Path(file).with_suffix(".tmp.mp3"))):
            try:
                Path(p).unlink()
            except Exception:
                pass


def chat(prompt: str, max_tokens: int = 600, timeout: int = 240,
         tier: str = "fast") -> str | None:
    """One chat call. tier: fast (SEO/classification) | strong (CEO).
    NVIDIA first; Groq free LLM as fallback when NVIDIA fails.
    Reasoning models put the answer in reasoning_content when content
    is null — handle both."""
    if API_KEY:
        model = MODEL_STRONG if tier == "strong" else MODEL_FAST
        try:
            r = requests.post(f"{BASE_URL}/chat/completions", json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens},
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=timeout)
            if r.status_code == 200:
                m = r.json()["choices"][0]["message"]
                out = m.get("content") or m.get("reasoning_content")
                if out:
                    return out
        except Exception:
            pass
    # Groq fallback (free tier; gpt-oss models are reasoning-type:
    # answer lands in "reasoning"/"reasoning_content" when content empty)
    if GROQ_API_KEY:
        try:
            r = requests.post(f"{GROQ_BASE}/chat/completions", json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens},
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                timeout=timeout)
            if r.status_code == 200:
                m = r.json()["choices"][0]["message"]
                return (m.get("content") or m.get("reasoning")
                          or m.get("reasoning_content") or "").strip() \
                    or None
        except Exception:
            pass
    return None
