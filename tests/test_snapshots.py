"""Snapshot store, set-relative salary scoring, filters, export (no network)."""
from fastapi.testclient import TestClient

from app import scoring, store
from app.main import app, apply_filters, summarize

client = TestClient(app)


def test_median_and_relative_outlier():
    jobs = [
        {"salary": "3 LPA", "description": "", "title": "a"},
        {"salary": "4 LPA", "description": "", "title": "b"},
        {"salary": "4.5 LPA", "description": "", "title": "c"},
    ]
    assert scoring.median_lpa(jobs) == 4.0
    assert scoring.median_lpa([{"salary": "", "description": "", "title": "x"}]) is None
    lure = scoring.normalize_job(
        {"title": "Fresher", "company_name": "X", "location": "B",
         "description": "freshers 12 LPA", "apply_options": [{"title": "A", "link": "https://a"}],
         "extensions": ["1 day ago"], "detected_extensions": {"posted_at": "1 day ago"}}
    )
    assert any("lure" in r for r in scoring.score_job(lure, set_median=4.0)["reasons"])
    normal = scoring.normalize_job(
        {"title": "Fresher", "company_name": "X", "location": "B",
         "description": "freshers 4 LPA", "apply_options": [{"title": "A", "link": "https://a"}],
         "extensions": ["1 day ago"], "detected_extensions": {"posted_at": "1 day ago"}}
    )
    assert not any("lure" in r for r in scoring.score_job(normal, set_median=4.0)["reasons"])


def test_summarize_and_filters():
    from app.main import run_pipeline

    data = run_pipeline("python", "Bengaluru")
    s = summarize(data["cards"])
    assert s["dist"]["green"] + s["dist"]["amber"] + s["dist"]["red"] == len(data["cards"])
    assert s["median_lpa"] is not None
    assert all(c["band"] != "red" for c in apply_filters(data["cards"], True, False))


def test_snapshots_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAP_PATH", str(tmp_path / "s.sqlite"))
    client.cookies.set("fs_vid", "tvisitor")
    from app.main import run_pipeline

    d1 = run_pipeline("python", "Bengaluru", visitor="tvisitor")
    assert d1["run_id"]
    runs = store.list_runs(visitor="tvisitor")
    assert len(runs) == 1 and runs[0]["n"] == 3
    d2 = run_pipeline("python", "Bengaluru", visitor="tvisitor")
    prev = store.previous_run("python", "Bengaluru", d2["run_id"], visitor="tvisitor")
    assert prev and prev["id"] == d1["run_id"]
    assert store.score_deltas(d2["cards"], prev["cards"])  # same fixtures overlap
    r = client.get("/export.csv", params={"role": "python", "run_id": d1["run_id"]})
    assert r.status_code == 200 and "HCL" in r.text and r.headers["content-type"].startswith("text/csv")
    assert client.get("/history").status_code == 200
    assert client.get(f"/history/{d1['run_id']}").status_code == 200


def test_history_reopens_same_ui(tmp_path, monkeypatch):
    """History entries reopen the SAME full pages — no separate mini UI."""
    monkeypatch.setenv("SNAP_PATH", str(tmp_path / "h.sqlite"))
    client.cookies.set("fs_vid", "tvisitor")
    from app.main import run_pipeline
    from app.agent import verify_paste

    d1 = run_pipeline("python", "Bengaluru", visitor="tvisitor")
    v = verify_paste("hello world test message about a job")
    import uuid

    from app import store as _store

    vid = _store.save_run("pasted message", "—", v["mode"], [v["card"]],
                          {"kind": "verify", "brain": v["brain"], "spent": v["spent"], "trace": v["trace"]},
                          visitor="tvisitor")
    search_page = client.get(f"/history/{d1['run_id']}").text
    assert "Why this score" in search_page and "snapshot" not in search_page.lower().replace("snapshots", "")
    verdict_page = client.get(f"/history/{vid}").text
    assert "Why I think so" in verdict_page and 'id="chat-form"' in verdict_page
    assert "run.html" not in verdict_page  # separate UI is gone
    hist = client.get("/history").text
    assert "Your past checks" in hist and "reopen the exact same page" in hist


def test_legacy_row_without_meta(tmp_path, monkeypatch):
    """DBs saved before the meta column still open."""
    import sqlite3

    monkeypatch.setenv("SNAP_PATH", str(tmp_path / "legacy.sqlite"))
    from app import store as _store

    c = sqlite3.connect(str(tmp_path / "legacy.sqlite"))
    c.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, role TEXT, location TEXT, mode TEXT, cards TEXT)")
    c.execute("INSERT INTO runs (ts, role, location, mode, cards) VALUES (1.0,'python','Bengaluru','FIXTURE','[]')")
    c.commit()
    c.close()
    run = _store.get_run(1)
    assert run and run["meta"] == {} and run["cards"] == []
    assert client.get("/history/1").status_code == 200


def test_runs_capped_at_50(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAP_PATH", str(tmp_path / "cap.sqlite"))
    from app import store as _store

    ids = [_store.save_run(f"r{i}", "Bengaluru", "FIXTURE", []) for i in range(55)]
    runs = _store.list_runs(limit=100)
    assert len(runs) == 50
    assert runs[0]["id"] == ids[-1]  # newest kept
    assert min(r["id"] for r in runs) == ids[-1] - 49  # oldest evicted


def test_cache_evicts_expired(tmp_path, monkeypatch):
    import sqlite3
    import time as _t

    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "c.sqlite"))
    from app import cache as _cache

    _cache.put("old", {"x": 1})
    c = sqlite3.connect(str(tmp_path / "c.sqlite"))
    c.execute("UPDATE serp_cache SET ts=?", (_t.time() - 99999,))
    c.commit()
    c.close()
    _cache.put("new", {"y": 2})
    assert _cache.get("old") is None and _cache.get("new") == {"y": 2}


def test_visitor_isolation(tmp_path, monkeypatch):
    """Two browsers, two worlds: histories, profiles, and run URLs don't leak."""
    from fastapi.testclient import TestClient as TC

    monkeypatch.setenv("SNAP_PATH", str(tmp_path / "iso.sqlite"))
    from app.main import app as _app
    from app import store as _store

    a, b = TC(_app), TC(_app)
    ra = a.post("/verify", data={"text": "hello world test message about a job"})
    assert ra.status_code == 200 and ra.cookies.get("fs_vid")
    assert "No saved checks yet" not in a.get("/history").text
    assert "No saved checks yet" in b.get("/history").text  # judge-fresh
    import re as _re

    rid = _re.search(r'name="run_id" value="(\d+)"', ra.text).group(1)
    assert b.get(f"/history/{rid}").status_code == 200  # renders, but...
    # ...b cannot see a's run: missing page (no leak of verdict content)
    assert "Why I think so" not in b.get(f"/history/{rid}").text
    assert "Why I think so" in a.get(f"/history/{rid}").text
    # profiles isolated too
    assert _store.get_profile("v-a") is None
    _store.save_profile("r.pdf", ["python"], "fresher", "x" * 300, visitor="v-a")
    assert _store.get_profile("v-b") is None
    assert _store.get_profile("v-a")["skills"] == ["python"]
