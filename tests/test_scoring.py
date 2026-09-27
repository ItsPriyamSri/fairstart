from app import scoring


def test_fee_scam_scores_red():
    j = scoring.normalize_job(
        {
            "title": "Software Developer HCL Hiring Freshers",
            "company_name": "HCL Technologies",
            "location": "Bengaluru",
            "via": "UnknownBoard",
            "extensions": ["3 days ago"],
            "detected_extensions": {"posted_at": "3 days ago"},
            "description": "Pay refundable registration fee Rs 2000 for interview ID. WhatsApp documents to hclfastservice@gmail.com",
            "apply_options": [],
        }
    )
    s = scoring.score_job(j)
    assert s["score"] >= 61 and s["band"] == "red"
    assert any("Fee" in r for r in s["reasons"])


def test_clean_listing_scores_green():
    j = scoring.normalize_job(
        {
            "title": "Python Developer (Fresher)",
            "company_name": "Nimbuspark Technologies",
            "location": "Bengaluru",
            "via": "Indeed",
            "extensions": ["2 days ago"],
            "detected_extensions": {"posted_at": "2 days ago", "salary": "3-4.5 LPA"},
            "description": "Freshers welcome. Apply via portal. No fees.",
            "apply_options": [{"title": "Indeed", "link": "https://example.com/a"}],
        }
    )
    s = scoring.score_job(j, news_hits=0, has_presence=True)
    assert s["score"] <= 30 and s["band"] == "green"


def test_dedupe_merges_reposts():
    a = scoring.normalize_job({"title": "Python Developer (Fresher)", "company_name": "Nimbuspark", "location": "Bengaluru, Karnataka", "apply_options": [{"title": "A", "link": "https://a"}]})
    b = scoring.normalize_job({"title": "Python Developer (Fresher)", "company_name": "Nimbuspark", "location": "Bengaluru, Karnataka", "apply_options": [{"title": "B", "link": "https://b"}]})
    out = scoring.dedupe([a, b])
    assert len(out) == 1 and out[0]["_dupes"] == 2 and len(out[0]["apply"]) == 2


def test_empty_and_malformed_handled():
    assert scoring.normalize_job({})["title"] == ""
    assert scoring.posted_days_ago(None) is None
    assert scoring.posted_days_ago("45 days ago") == 45
    s = scoring.score_job(scoring.normalize_job({}))
    assert 0 <= s["score"] <= 100
