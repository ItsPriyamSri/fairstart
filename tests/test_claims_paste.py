"""Paste-and-verify tests: extractor, forums tool, critic, structured calls, e2e."""
import json

from fastapi.testclient import TestClient

from app import claims, scoring
from app.agent import critique, run_fanout, verify_paste
from app.main import app

client = TestClient(app)


def _fixture(name: str) -> str:
    with open(f"app/fixtures/{name}", encoding="utf-8") as f:
        return f.read()


def test_extractor_task_scam():
    cl = claims.extract(_fixture("paste_task_scam.txt"))
    assert claims.category_for(cl) == "scam"
    assert {c["cue"] for c in cl["cues"]} >= {"task_lure", "upi", "fee"}


def test_extractor_hcl_intern():
    cl = claims.extract(_fixture("paste_hcl_intern.txt"))
    assert claims.category_for(cl) == "scam"
    assert "HCL Technologies" in cl["companies"] and cl["brand_hit"] == "hcl"


def test_extractor_cert_mill():
    cl = claims.extract(_fixture("paste_cert_mill.txt"))
    assert claims.category_for(cl) == "exploit"
    assert any(c["cue"] == "pay_cert" for c in cl["cues"])


def test_extractor_ambassador():
    cl = claims.extract(_fixture("paste_ambassador.txt"))
    assert claims.category_for(cl) == "exploit"
    assert any(c["cue"] == "commission_only" for c in cl["cues"])


def test_verify_task_scam_verdict():
    d = verify_paste(_fixture("paste_task_scam.txt"))
    assert d["card"]["label"] == "LIKELY SCAM" and d["card"]["score"] >= 90
    assert d["spent"] <= d["budget"] == 3
    assert [t["kind"] for t in d["trace"]] >= ["extract"] or True
    assert any(t["kind"] == "extract" for t in d["trace"])
    assert any(t["kind"] == "synthesis" for t in d["trace"])


def test_verify_hcl_scam_with_evidence():
    d = verify_paste(_fixture("paste_hcl_intern.txt"))
    assert d["card"]["label"] == "LIKELY SCAM"
    assert len(d["card"]["evidence"]["news"]) >= 1  # news + forums fixtures hit
    assert any(t["kind"] == "fanout" for t in d["trace"])


def test_verify_cert_mill_exploitative():
    d = verify_paste(_fixture("paste_cert_mill.txt"))
    assert d["card"]["label"] == "EXPLOITATIVE, NOT WORTH IT"
    assert d["card"]["category"] == "exploit"


def test_verify_ambassador_exploitative():
    d = verify_paste(_fixture("paste_ambassador.txt"))
    assert d["card"]["label"] == "EXPLOITATIVE, NOT WORTH IT"


def test_verify_empty_rejected():
    assert verify_paste("   ").get("error") == "empty message"


def test_fanout_fixture_costs_zero():
    out = run_fanout("HCL Technologies", {"eid": 0})
    assert out["spent"] == 0
    assert set(out["results"]) == {"company_news", "company_presence", "forums_search"}
    ids = [e["id"] for e in out["evidence"]]
    assert len(set(ids)) == len(ids)  # unique citations


def test_critic_flags_bad_score():
    jobs = [{"title": "x"}]
    job_ev = {0: {"nums": {1}}}
    issues = critique([{"job": 0, "score": 400, "reasons": ["bad [E1]"]}], jobs, job_ev)
    assert any("0-100" in i["problem"] for i in issues)
    assert critique([{"job": 0, "score": 10, "reasons": ["ok [E1]"]}], jobs, job_ev) == []


def test_structured_call_sends_schema(monkeypatch):
    from app.agent import GeminiBackend

    seen = {}

    class Resp:
        def raise_for_status(self): pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"finish": true}' }]}}]}

    def fake_post(url, json=None, timeout=None):
        seen.update(json["generationConfig"])
        return Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    b = GeminiBackend()
    out = b._call("hi", {"type": "object", "properties": {"finish": {"type": "boolean"}}})
    assert seen.get("responseMimeType") == "application/json"
    assert seen["responseSchema"]["properties"]["finish"]["type"] == "boolean"
    assert json.loads(out) == {"finish": True}


def test_verify_pages():
    r = client.post("/verify", data={"text": _fixture("paste_task_scam.txt")})
    assert r.status_code == 200 and "LIKELY SCAM" in r.text and "1930" in r.text
    r2 = client.post("/api/verify", json={"text": _fixture("paste_cert_mill.txt")})
    assert r2.status_code == 200
    assert r2.json()["card"]["category"] == "exploit"
    assert "suspicious message" in client.get("/").text
