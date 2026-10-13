"""Task parser — turns a natural-language chat task into
structured actions the dashboard can execute.

Examples:
  "comment Great post on https://instagram.com/reel/ABC with Main IG,
   Second IG"
  "open Main IG"
  "post my title to Main IG"

Uses an LLM (Omniroute) when available for free-form parsing;
falls back to regex templates so it always works.
"""
from __future__ import annotations

import json
import re

import requests

OMNIRUTE_URL = "http://localhost:20128/v1/chat/completions"


def _llm(prompt: str, max_tokens: int = 600) -> str | None:
    import llm
    return llm.chat(prompt, max_tokens=max_tokens)


def parse_task(text: str, account_names: list[str]) -> list[dict]:
    """Parse a chat task into a list of action dicts.

    Each action: {"action": "comment"|"open"|"post", ...}
    """
    text = (text or "").strip()
    if not text:
        return []

    # Try LLM first for free-form parsing
    llm_out = _llm(
        f"Parse this social-media task into JSON actions. "
        f"Available Instagram account names: {account_names}.\n"
        f"Task: {text}\n"
        f"Return a JSON array of actions. Each action is one of:\n"
        f'  {{"action":"comment","url":"...","text":"...",'
        f'"accounts":["..."]}}\n'
        f'  {{"action":"open","account":"..."}}\n'
        f'  {{"action":"post","account":"...","title":"...",'
        f'"description":"..."}}\n'
        f"Only use the exact account names given. If unclear, "
        f"return an empty array [].")
    if llm_out:
        # reasoning models echo the prompt template — extract balanced
        # [...] arrays, last first, reject placeholder-only ones
        candidates: list[str] = []
        depth = 0
        start = -1
        for i, ch in enumerate(llm_out):
            if ch == "[":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "]":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start >= 0:
                        candidates.append(llm_out[start:i + 1])
                        start = -1
        for cand in reversed(candidates):
            try:
                actions = json.loads(cand)
            except Exception:
                continue
            if (isinstance(actions, list) and actions
                    and all(isinstance(a, dict) for a in actions)):
                return actions

    # Regex template fallback
    actions: list[dict] = []
    low = text.lower()

    # "campaign" / "campain" / "scout op" / "grow" → run the CEO company
    if re.search(r"campain|campaign|scout|grow", low):
        # topic = the text minus command words
        topic = re.sub(
            r"\b(scout|op|all|campain|campaign|grow|grow account|run|make|"
            r"do|start|launch|my|account|the)\b", " ", text,
            flags=re.I)
        topic = re.sub(r"\s+", " ", topic).strip()
        if re.search(r"^grow\b", low):
            return [{"action": "grow",
                     "target": topic or "our accounts"}]
        return [{"action": "campaign",
                 "topic": topic or text}]

    # "comment <text> on <url> with/using <accounts>"
    mc = re.search(
        r"comment\s+(.+?)\s+on\s+(https?://\S+)"
        r"(?:\s+(?:with|using|from)\s+(.+))?", text, re.I)
    if mc:
        ctext, url, accts = mc.groups()
        names = _match_accounts(accts or "", account_names)
        actions.append({"action": "comment", "url": url,
                          "text": ctext.strip(),
                          "accounts": names or account_names})
        return actions

    # "open <account>"
    mo = re.search(r"open\s+(.+)", text, re.I)
    if mo:
        names = _match_accounts(mo.group(1), account_names)
        for n in names:
            actions.append({"action": "open", "account": n})
        if actions:
            return actions

    # "post <title> to <account>"
    mp = re.search(
        r"post\s+(.+?)\s+(?:to|on)\s+(.+)", text, re.I)
    if mp:
        title, accts = mp.groups()
        names = _match_accounts(accts, account_names)
        for n in names:
            actions.append({"action": "post", "account": n,
                              "title": title.strip(),
                              "description": ""})
        if actions:
            return actions

    # ANY other task → run the FULL company (CEO + all workers).
    # The user just types a task; the agents do all the work.
    return [{"action": "campaign", "topic": text}]


def _match_accounts(text: str, account_names: list[str]) -> list[str]:
    """Find which known account names appear in the text."""
    found = []
    for name in account_names:
        if name and name.lower() in text.lower():
            found.append(name)
    return found
