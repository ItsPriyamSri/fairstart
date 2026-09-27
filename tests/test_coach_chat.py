"""Big-brother voice + safe-space chat tests (grounded or bust)."""
from fastapi.testclient import TestClient

from app import coach
from app.agent import chat_answer, verify_paste
from app.main import app

client = TestClient(app)


def _scam_card():
    d = verify_paste(open("app/fixtures/paste_task_scam.txt", encoding="utf-8").read())
    return d["card"]


def test_coach_voice_present():
    card = _scam_card()
    assert "single rupee" in card["coach"]["opener"]
    assert len(card["coach"]["cons"]) >= 3
    assert any("UPI" in c["con"] for c in card["coach"]["cons"])
    assert "🤝" in card["coach"]["closer"]
    # cons carry the student's own quoted words
    assert all(c["quote"] for c in card["coach"]["cons"])


def test_coach_voice_all_categories():
    for cat in ["scam", "exploit", "bond", "selfharm", "unverifiable", "clean", "weird"]:
        assert coach.opener_for(cat) and coach.closer_for(cat)
        assert "victim" not in coach.opener_for(cat).lower()  # blame scammer, never student


def test_reply_intents():
    card = _scam_card()
    assert "faith" in coach.deterministic_reply("why this score?", card, []).lower()
    assert "1930" in coach.deterministic_reply("I already paid, what now?", card, [])
    push = coach.deterministic_reply("but my friend got paid, looks real?", card, [])
    assert "video" in push and str(card["score"]) in push  # holds line, offers test
    assert "Straight answer" in coach.deterministic_reply("should I join?", card, [])
    fb = coach.deterministic_reply("tell me about the weather", card, [])
    assert str(card["score"]) in fb  # falls back to verdict, never invents


def test_chat_answer_thread_and_honesty():
    card = _scam_card()
    r1 = chat_answer("t-test", card, "why?")
    assert r1["via"] == "rules" and len(r1["thread"]) == 1
    r2 = chat_answer("t-test", card, "should I join?")
    assert len(r2["thread"]) == 2  # thread accumulates
    r3 = chat_answer("t-fresh", card, "")
    assert "Ask me anything" in r3["reply"] and r3["thread"] == []


def test_gemini_chat_path_mocked(monkeypatch):
    from app.agent import GeminiBackend
    from app import config

    monkeypatch.setattr(config, "GEMINI_API_KEY", "DUMMY")
    monkeypatch.setattr(GeminiBackend, "_call", lambda self, p, s=None: "Warm mocked answer. 🤝")
    card = _scam_card()
    r = chat_answer("t-mock", card, "why?", backend=GeminiBackend())
    assert r["reply"].startswith("Warm mocked") and r["via"].startswith("gemini")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")


def test_chat_route_flow():
    r = client.post("/verify", data={"text": open("app/fixtures/paste_hcl_intern.txt", encoding="utf-8").read()})
    assert r.status_code == 200 and "single rupee" in r.text and "What you could lose" in r.text
    import re

    run_id = re.search(r'name="run_id" value="(\d+)"', r.text).group(1)
    thread_id = re.search(r'name="thread_id" value="([a-f0-9]+)"', r.text).group(1)
    c = client.post("/chat", data={"run_id": run_id, "idx": 0, "thread_id": thread_id,
                                   "question": "but their website looks real?"})
    assert c.status_code == 200 and "video" in c.text  # pushback handled warmly
    c2 = client.post("/api/chat", json={"run_id": int(run_id), "idx": 0,
                                        "thread_id": thread_id, "question": "why?"})
    assert c2.status_code == 200 and len(c2.json()["thread"]) == 2


def test_premium_ui_wired():
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    index = client.get("/").text
    assert "style.css" in index and "pill-link" in index
    v = client.post("/verify", data={"text": "hello world test message about a job"}).text
    assert 'id="thread"' in v and 'id="chat-form"' in v and "app.js" in v


def test_stream_flow_offline():
    r = client.post("/go/verify", data={"text": "hello world test message about a job"})
    assert r.status_code == 200 and "EventSource" in r.text and "/stream/" in r.text
    import re as _re

    token = _re.search(r"/stream/([a-f0-9]+)", r.text).group(1)
    import threading, time

    for _ in range(60):
        r2 = client.get(f"/view/{token}")
        if "Verdict" in r2.text or "LIKELY" in r2.text or "WORTH A LOOK" in r2.text or "UNVERIFIABLE" in r2.text:
            break
        time.sleep(0.5)
    assert "FairStart" in r2.text
    r3 = client.post("/go/search", data={"role": "python", "location": "Bengaluru"})
    assert r3.status_code == 200 and "EventSource" in r3.text
