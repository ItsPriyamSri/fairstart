"""Resume Match%, gaps, interview prep, fake→real loop tests."""
from fastapi.testclient import TestClient

from app import interview, resume
from app.main import app

client = TestClient(app)

RESUME_TEXT = ("Aarav Kumar, B.Tech CSE 2026. Skills: Python, Django, SQL, Git, HTML, CSS, "
               "JavaScript. Projects: blog app with Django REST. 6-month internship experience.")


def _pdf_bytes(text: str = ("Python Django SQL Fresher Git HTML CSS JavaScript REST API "
                               "BTech CSE 2026 projects blog app testing Linux Docker "
                               "machine learning basics data structures algorithms " * 3)) -> bytes:
    body = (f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET").encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    out += f"trailer\n<< /Root 1 0 R >>\nstartxref\n0\n%%EOF\n".encode()
    return out


def test_extract_skills_and_level():
    f = resume.extract_skills(RESUME_TEXT)
    assert {"python", "django", "sql", "git"} <= set(f["skills"])
    assert f["level"] == "fresher"
    assert resume.extract_skills("Senior engineer, 8 years experience, lead")["level"] == "experienced"


def test_match_pct_and_gaps():
    prof = {"skills": ["python", "django", "sql"]}
    m = resume.match("Need python, django and docker for backend role", prof)
    assert m["pct"] == 67 and m["missing"] == ["docker"]
    assert resume.match("Great team, apply soon!", prof)["pct"] is None


def test_parse_pdf_paths():
    ok = resume.parse_pdf(_pdf_bytes())
    assert ok["ok"] and "Python" in ok["text"]
    assert not resume.parse_pdf(b"hello")["ok"]
    assert not resume.parse_pdf(b"%PDF" + b"x" * 10)["ok"]
    assert not resume.parse_pdf(b"%PDF-1.4 " + b"y" * (2 * 1024 * 1024 + 1))["ok"]
    assert not resume.parse_pdf(b"%PDF-1.4\nno text here at all")["ok"]


def test_interview_maps():
    assert interview.role_for("Django backend developer") == "python"
    assert interview.role_for("React UI engineer") == "frontend"
    assert interview.role_for("something exotic") == "general"
    plan = interview.seven_day_plan("python", ["docker"])
    assert len(plan) == 7 and "docker" in plan[5]
    assert len(interview.QBANK["python"]) >= 2


def test_profile_upload_and_match_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAP_PATH", str(tmp_path / "s.sqlite"))
    r = client.post("/profile", files={"resume": ("r.pdf", _pdf_bytes(), "application/pdf")})
    assert r.status_code == 200 and "Saved" in r.text and "django" in r.text
    assert client.get("/profile").status_code == 200
    s = client.get("/api/search", params={"role": "python", "location": "Bengaluru"}).json()
    assert s["cards"][0]["match"] is not None  # Match% attached (profile present)


def test_fake_to_real_loop():
    from app.agent import verify_paste

    d = verify_paste(open("app/fixtures/paste_task_scam.txt", encoding="utf-8").read())
    assert d["card"]["search_link"].startswith("/search?role=")


def test_chat_jobs_prep_quiz_intents():
    from app import coach
    from app.agent import verify_paste

    d = verify_paste(open("app/fixtures/paste_task_scam.txt", encoding="utf-8").read())
    card = d["card"]
    card["search_link"] = "/search?role=intern&location=India"
    assert "/search?role=" in coach.deterministic_reply("find me real internships please", card, [])
    assert "Day 1" in coach.deterministic_reply("make me a study plan", card, [])
    assert "Practice Q" in coach.deterministic_reply("quiz me now", card, [])


def test_chat_api_bad_run():
    r = client.post("/api/chat", json={"run_id": 99999, "idx": 0, "thread_id": "t", "question": "hi"})
    assert r.status_code == 404
