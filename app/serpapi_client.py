"""SerpApi client: bounded, timed-out, single retry on 429/5xx only.

Engines used: google_jobs (primary), google_news + google (verification).
Only successful searches spend credits upstream; cached/errored/failed are free.
"""
import json
import time
import urllib.parse

import httpx

from . import cache, config

RETRYABLE = {429, 500, 502, 503, 504}


def cache_key(engine: str, params: dict) -> str:
    items = sorted((k, str(v)) for k, v in params.items() if k != "api_key")
    return engine + "|" + urllib.parse.urlencode(items)


def search(engine: str, params: dict, timeout: float | None = None, retries: int = 1) -> dict:
    """Live SerpApi call. Raises RuntimeError with safe (key-free) message on failure."""
    if not config.SERPAPI_API_KEY:
        raise RuntimeError("SERPAPI_API_KEY not configured")
    timeout = timeout if timeout is not None else config.SERPAPI_TIMEOUT_S
    q = dict(params)
    q["engine"] = engine
    q["api_key"] = config.SERPAPI_API_KEY
    key = cache_key(engine, params)
    hit = cache.get(key)
    if hit is not None:
        return {"_cache": "local-hit", **hit}
    last_err = "unknown"
    for attempt in range(retries + 1):
        try:
            r = httpx.get(config.SERPAPI_BASE, params=q, timeout=timeout)
            if r.status_code in RETRYABLE and attempt < retries:
                last_err = f"HTTP {r.status_code}"
                time.sleep(1.0)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"SerpApi HTTP {r.status_code}")
            data = r.json()
            if (
                isinstance(data, dict)
                and data.get("search_metadata", {}).get("status") == "Error"
            ):
                raise RuntimeError(data.get("error", "SerpApi search error"))
            cache.put(key, data)
            return data
        except RuntimeError:
            raise
        except Exception as e:  # network/timeout/JSON
            last_err = f"{type(e).__name__}"
            if attempt < retries:
                time.sleep(1.0)
                continue
            raise RuntimeError(f"SerpApi request failed: {last_err}")
    raise RuntimeError(f"SerpApi request failed: {last_err}")


def jobs(q: str, location: str) -> dict:
    params = {"q": q, "location": location, "hl": "en", "gl": "in"}
    return search("google_jobs", params)


def _fast(ctx: dict) -> dict:
    """Fan-out calls fail fast (10s, no retry): one slow check must never
    hold the whole verdict hostage when sibling evidence suffices."""
    return {"timeout": 10, "retries": 0} if ctx.get("fast") else {}


def company_news(company: str, ctx: dict | None = None) -> dict:
    return search(
        "google_news",
        {"q": f'"{company}" scam OR fraud OR layoff OR fake jobs', "hl": "en", "gl": "in"},
        **_fast(ctx or {}),
    )


def company_presence(company: str, ctx: dict | None = None) -> dict:
    return search(
        "google", {"q": f'"{company}" official site careers reviews', "hl": "en", "gl": "in"},
        **_fast(ctx or {}),
    )


def forums(company: str, ctx: dict | None = None) -> dict:
    """Victim threads: Reddit/forum scam discussions. Cost: 1 (0 in fixture)."""
    return search(
        "google_forums",
        {"q": f'"{company}" scam OR fraud OR fake internship', "hl": "en", "gl": "in"},
        **_fast(ctx or {}),
    )


def load_fixture(name: str) -> dict:
    import os

    with open(os.path.join(config.FIXTURE_DIR, name), encoding="utf-8") as f:
        return json.load(f)
