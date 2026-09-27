"""URL verdicts: fetch JD text, judge it, fail honestly."""
from fastapi.testclient import TestClient

from app.agent import fetch_url_text
from app.main import app

client = TestClient(app)

SCAM_HTML = """<html><head><title>x</title><script>var a=1;</script></head><body>
<h1>HCL Technologies Internship - direct selection, no interview</h1>
<p>Pay refundable registration fee Rs 2500 on WhatsApp to hclselect@gmail.com. """
SCAM_HTML += "Guaranteed PPO and stipend Rs 25000 per month. " * 12 + "</p></body></html>"


class FakeResp:
    status_code = 200
    content = SCAM_HTML.encode()
    text = SCAM_HTML
    url = "https://example.com/jobs/123"


def _mock(monkeypatch, resp=None, exc=None):
    import httpx

    def fake_get(*a, **k):
        if exc:
            raise exc
        return resp or FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)


def test_fetch_ok_strips_markup(monkeypatch):
    _mock(monkeypatch)
    r = fetch_url_text("https://example.com/jobs/123")
    assert r["ok"] and "var a=1" not in r["text"] and "registration fee" in r["text"]


def test_fetch_rejects_bad_scheme():
    assert fetch_url_text("notaurl")["ok"] is False
    assert fetch_url_text("ftp://x/y")["ok"] is False


def test_fetch_short_page_honest(monkeypatch):
    class Tiny(FakeResp):
        text = "<html><body><div id=app></div></body></html>"
        content = b"<html><body><div id=app></div></body></html>"

    _mock(monkeypatch, Tiny())
    r = fetch_url_text("https://example.com/app")
    assert not r["ok"] and "paste the text" in r["error"]


def test_fetch_network_error_honest(monkeypatch):
    _mock(monkeypatch, exc=ConnectionError("down"))
    r = fetch_url_text("https://example.com/x")
    assert not r["ok"] and "paste the text" in r["error"]


def test_verify_url_route_scam(monkeypatch):
    _mock(monkeypatch)
    r = client.post("/verify-url", data={"url": "https://example.com/jobs/123"})
    assert r.status_code == 200 and "LIKELY SCAM" in r.text and "example.com/jobs/123" in r.text


def test_verify_url_route_bad(monkeypatch):
    _mock(monkeypatch, exc=TimeoutError("t"))
    r = client.post("/verify-url", data={"url": "https://example.com/x"})
    assert r.status_code == 200 and "paste the text" in r.text
