"""Calibration tests: floors, benchmark lure, thin-evidence honesty, merged input."""
from app import claims, scoring
from app.agent import verify_paste

CLEAN = ("Nimbuspark Technologies is hiring a python intern in Bengaluru. "
         "Stipend Rs 8000 per month. Apply on our careers page. "
         "Two video interview rounds. No fees at any stage.")


def test_fee_floor_overrides_presence():
    job = {"title": "x", "company": "Y", "location": "B", "via": "m",
           "description": "Pay refundable registration fee Rs 2000. Official site exists.",
           "apply": [{"title": "A", "link": "https://a"}], "extensions": ["1 day ago"],
           "detected_extensions": {"posted_at": "1 day ago"}}
    j = scoring.normalize_job({**job, "company_name": "Y", "apply_options": [{"title": "A", "link": "https://a"}]})
    s = scoring.score_paste(j, [{"cue": "fee", "family": "fraud", "quote": "registration fee"}],
                            has_presence=True)
    assert s["score"] >= 61  # contradiction rule: scam evidence beats shiny site


def test_benchmark_lure_flagged():
    assert any(v >= 4 * scoring.AVG_STIPEND_MONTHLY
               for v in scoring.monthly_inr("Earn Rs 5000 per day from home"))
    assert scoring.monthly_inr("Stipend Rs 8000 per month") == [8000.0]
    j = scoring.normalize_job({"title": "t", "company_name": "X", "location": "B",
                               "description": "Earn Rs 5000 per day, no experience",
                               "apply_options": [{"title": "A", "link": "https://a"}],
                               "extensions": ["1 day ago"],
                               "detected_extensions": {"posted_at": "1 day ago"}})
    s = scoring.score_paste(j, [])
    assert any("lure sizing" in r for r in s["reasons"])


def test_thin_evidence_never_genuine():
    assert claims.label_for(10, "clean", proof=False) == "WORTH A LOOK — verify first"
    assert claims.label_for(10, "clean", proof=True) == "LIKELY GENUINE"
    assert claims.label_for(10, "unverifiable") == "UNVERIFIABLE — caution, not proof"


def test_clean_known_company_genuine():
    d = verify_paste(CLEAN)
    assert d["card"]["label"] == "LIKELY GENUINE", d["card"]["label"]
    assert d["card"]["score"] <= 30


def test_clean_unknown_company_capped():
    d = verify_paste("SomeBrandX Labs hiring python intern. Stipend Rs 8000/month. "
                     "Apply on careers page. Video interviews.")
    assert d["card"]["label"] in ("WORTH A LOOK — verify first", "UNVERIFIABLE — caution, not proof")
    assert d["card"]["label"] != "LIKELY GENUINE"


def test_merged_text_plus_url(monkeypatch):
    import httpx

    html = ("<html><body><h1>Task job: like videos, earn Rs 5000 per day.</h1><p>"
            + "Pay refundable deposit Rs 2000 to unlock tasks on Telegram. " * 10 + "</p></body></html>")

    class Resp:
        status_code = 200
        content = html.encode()
        text = html
        url = "https://shady.example/jobs/9"

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Resp())
    d = verify_paste("Friend forwarded this, is it real? https://shady.example/jobs/9")
    assert d["card"]["label"] == "LIKELY SCAM"
    assert d["card"]["source_url"] == "https://shady.example/jobs/9"
    assert any(t.get("tool") == "fetch_url" and t.get("ok") for t in d["trace"])
