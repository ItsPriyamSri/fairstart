"""Adapter tests with mocked HTTP + fixture responses (no live calls)."""
import app.serpapi_client as api
from app import config


def test_cache_key_ignores_api_key():
    assert api.cache_key("google_jobs", {"q": "x", "api_key": "SECRET"}) == api.cache_key(
        "google_jobs", {"q": "x", "api_key": "OTHER"}
    )


def test_fixture_loads_and_normalizes():
    from app import scoring

    raw = api.load_fixture("jobs_bengaluru_python.json")
    assert len(raw["jobs_results"]) == 4
    jobs = scoring.dedupe([scoring.normalize_job(j) for j in raw["jobs_results"]])
    assert len(jobs) == 3  # nimbuspark dup merged
    assert not config.SERPAPI_API_KEY or True  # live key optional; fixture path is default


def test_search_requires_key(monkeypatch):
    monkeypatch.setattr(config, "SERPAPI_API_KEY", "")
    try:
        api.search("google_jobs", {"q": "x"})
    except RuntimeError as e:
        assert "not configured" in str(e)
    else:
        raise AssertionError("should have raised")
