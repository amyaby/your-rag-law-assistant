"""Probe which Gemini model ids this API key can actually use.

Gemini 2.x models were retired for new accounts (404 NOT_FOUND), which
silently broke the fallback chain in `app/core/llm.py`. Run this after changing
`LLM_MODEL` or `LLM_FALLBACK_MODELS` to confirm every id in the chain is live.

Run:  ./venv/bin/python scripts/probe_models.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google import genai

from app.config import settings

client = genai.Client(api_key=settings.gemini_api_key)

CANDIDATES = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-flash-latest",
]

ok, dead, rate = [], [], []
for m in CANDIDATES:
    try:
        r = client.models.generate_content(model=m, contents="Reply with the single word: OK")
        text = (r.text or "").strip()
        if text:
            ok.append(m)
            print(f"  [ OK ] {m:28} -> {text[:30]!r}")
        else:
            rate.append(m)
            print(f"  [EMPTY] {m:28} -> no text")
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            rate.append(m)
            print(f"  [RATE] {m:28} -> {msg[:110]}")
        else:
            dead.append(m)
            print(f"  [DEAD] {m:28} -> {msg[:110]}")

print("\nUSABLE :", ok)
print("DEAD   :", dead)
print("RATE   :", rate)
print("\nRecommended chain:", (ok + rate + [])[:3])
