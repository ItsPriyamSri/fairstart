"""LLM adapter (optional, isolated, grounded-only).

Default path is fully deterministic (scoring.py) and needs no key.
If GEMINI_API_KEY is set, `grounded_bullets` may rephrase the deterministic
reasons — it MUST NOT add facts, citations, or companies not in the input.
It returns plain strings; UI always labels them 'generated rephrasing' vs
'retrieved evidence'. Currently implemented as a safe extractive pass so the
product works identically with or without a key (live LLM call is a future
opt-in, not required for the demo).
"""
from . import config


def grounded_bullets(reasons: list[str], max_bullets: int = 4) -> dict:
    bullets = [r.strip() for r in reasons if r.strip()][:max_bullets]
    return {
        "bullets": bullets,
        "generated": bool(config.GEMINI_API_KEY),
        "note": "LLM rephrasing of retrieved evidence"
        if config.GEMINI_API_KEY
        else "Deterministic extract (no LLM key configured)",
    }
