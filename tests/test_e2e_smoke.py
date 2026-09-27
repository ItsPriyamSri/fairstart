"""End-to-end smoke: fixture pipeline -> scored cards, no network."""
from fastapi.testclient import TestClient

from app.main import app, run_pipeline

client = TestClient(app)


def test_pipeline_fixture_mode():
    data = run_pipeline("python", "Bengaluru")
    assert data["mode"].startswith("FIXTURE")
    assert len(data["cards"]) == 3
    scores = {c["company"] or "UNKNOWN": c["score"] for c in data["cards"]}
    assert scores["HCL Technologies"] > scores["Nimbuspark Technologies"]
    # provenance present
    hcl = next(c for c in data["cards"] if c["company"] == "HCL Technologies")
    assert hcl["evidence"]["news"], "scam-pattern company must carry news evidence"


def test_http_pages():
    assert client.get("/healthz").json()["ok"] is True
    assert client.get("/").status_code == 200
    r = client.get("/search", params={"role": "python", "location": "Bengaluru"})
    assert r.status_code == 200
    assert "FIXTURE" in r.text or "Recorded-fixture" in r.text
    r2 = client.get("/api/search", params={"role": "python", "location": "Bengaluru"})
    assert r2.status_code == 200 and len(r2.json()["cards"]) == 3
