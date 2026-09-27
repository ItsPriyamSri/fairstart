"""FastAPI app: fresher job search -> dedup -> trust cards with provenance."""
import os
import uuid
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, interview, resume, scoring, store
from .agent import chat_answer, fetch_url_text, run_agent, verify_paste

app = FastAPI(title="FirstJob Verifier")
BASE = os.path.dirname(os.path.dirname(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
if os.path.isdir(os.path.join(BASE, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


def live_mode() -> bool:
    return bool(config.SERPAPI_API_KEY)


def summarize(cards: list[dict]) -> dict:
    """Result-set stats, all local compute (zero SerpApi cost)."""
    import re

    dist = {"green": 0, "amber": 0, "red": 0}
    for c in cards:
        dist[c["band"]] += 1
    med = scoring.median_lpa(cards)
    days = [scoring.posted_days_ago(c.get("posted_at")) for c in cards]
    days = [d for d in days if d is not None]
    senior = sum(
        1 for c in cards
        if re.search(r"senior|lead|manager|architect|\b[5-9]\+?\s*(yr|year)", f"{c['title']} {c.get('description','')}", re.I)
    )
    return {
        "dist": dist,
        "median_lpa": med,
        "freshest_days": min(days) if days else None,
        "stale_n": sum(1 for d in days if d > 30),
        "senior_n": senior,
    }


def apply_filters(cards: list[dict], hide_risky: bool, hide_senior: bool) -> list[dict]:
    import re

    out = cards
    if hide_risky:
        out = [c for c in out if c["band"] != "red"]
    if hide_senior:
        out = [
            c for c in out
            if not re.search(r"senior|lead|manager|architect|\b[5-9]\+?\s*(yr|year)",
                             f"{c['title']} {c.get('description','')}", re.I)
        ]
    return out


def run_pipeline(role: str, location: str) -> dict:
    """One agentic run: plan -> act (SerpApi tools) -> synthesize -> snapshot."""
    data = run_agent(role, location)
    enrich(data["cards"])
    try:
        run_id = store.save_run(role, location, data["mode"], data["cards"],
            {"kind": "search", "brain": data.get("brain", ""), "spent": data.get("spent", 0), "trace": data.get("trace", [])})
    except Exception:
        run_id = None
    data["summary"] = summarize(data["cards"])
    data["run_id"] = run_id
    return data


def enrich(cards: list[dict]) -> None:
    """Resume Match% + interview prep topics on each card (all local, free)."""
    profile = None
    try:
        profile = store.get_profile()
    except Exception:
        pass
    for c in cards:
        text = f"{c.get('title','')}\n{c.get('description','')}"
        role = interview.role_for(text)
        c["prep_role"] = role
        c["prep"] = interview.TOPICS[role][:3]
        c["match"] = resume.match(text, profile) if profile else None


@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": "LIVE" if live_mode() else "FIXTURE",
            "brain": "gemini:" + config.GEMINI_MODEL if config.GEMINI_API_KEY else "deterministic",
            "budget": 1 + 3 * config.MAX_VERIFY_COMPANIES}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"mode": "LIVE" if live_mode() else "FIXTURE"}
    )


@app.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    role: str = Query("python", max_length=80),
    location: str = Query("Bengaluru", max_length=80),
    hide_risky: bool = False,
    hide_senior: bool = False,
):
    data = run_pipeline(role.strip() or "python", location.strip() or "Bengaluru")
    data["cards"] = apply_filters(data["cards"], hide_risky, hide_senior)
    data["summary"] = summarize(data["cards"])
    data["hide_risky"] = hide_risky
    data["hide_senior"] = hide_senior
    return templates.TemplateResponse(request, "results.html", data)


@app.get("/api/search")
def search_api(
    role: str = Query("python", max_length=80),
    location: str = Query("Bengaluru", max_length=80),
):
    return JSONResponse(run_pipeline(role.strip() or "python", location.strip() or "Bengaluru"))


@app.get("/export.csv")
def export_csv(run_id: int = Query(0)):
    import csv
    import io

    run = store.get_run(run_id)
    if not run:
        return JSONResponse({"error": "snapshot not found"}, status_code=404)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["title", "company", "location", "via", "posted_at", "salary",
                "score", "band", "reasons", "apply_link", "share_link"])
    for c in run["cards"]:
        w.writerow([c["title"], c["company"], c["location"], c["via"],
                    c.get("posted_at") or "", c.get("salary") or "", c["score"],
                    c["band"], " | ".join(c["reasons"]),
                    c["apply"][0]["link"] if c["apply"] else "", c.get("share_link") or ""])
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=firstjob-{run_id}.csv"})


@app.post("/verify", response_class=HTMLResponse)
async def verify_page(request: Request):
    form = dict(await request.form())
    text = (form.get("text") or "").strip()
    if not text:
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE"})
    data = verify_paste(text)
    if "card" not in data:
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE",
                                           "form_error": "Paste a message first."})
    card = data["card"]
    _enrich_paste_card(card)
    try:
        data["run_id"] = store.save_run("pasted message", "—", data["mode"], [data["card"]],
            {"kind": "verify", "brain": data.get("brain", ""), "spent": data.get("spent", 0), "trace": data.get("trace", [])})
    except Exception:
        data["run_id"] = None
    data["thread_id"] = uuid.uuid4().hex[:8]
    data["thread"] = []
    data["idx"] = 0
    return templates.TemplateResponse(request, "verdict.html", data)


@app.post("/api/verify")
async def verify_api(request: Request):
    body = await request.json()
    return JSONResponse(verify_paste((body or {}).get("text", "")))


@app.post("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Follow-up chat about a verdict. Threads live in server memory (demo scope)."""
    form = dict(await request.form())
    try:
        run_id, idx = int(form.get("run_id", 0)), int(form.get("idx", 0))
    except ValueError:
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE"})
    run = store.get_run(run_id)
    if not run or not (0 <= idx < len(run["cards"])):
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE"})
    thread_id = form.get("thread_id") or "t0"
    data = chat_answer(thread_id, run["cards"][idx], form.get("question", ""))
    card = dict(run["cards"][idx])
    card["summary"] = {"bullets": card.get("reasons", [])}
    return templates.TemplateResponse(request, "verdict.html",
                                      {"mode": run["mode"], "card": card,
                                       "errors": [], "trace": [{"kind": "chat", "note": f"{len(data['thread'])} exchanges"}],
                                       "spent": 0, "budget": 3, "brain": data["via"],
                                       "run_id": run_id, "idx": idx,
                                       "thread_id": thread_id, "thread": data["thread"]})


@app.post("/verify-url", response_class=HTMLResponse)
async def verify_url_page(request: Request):
    """Judge a posting URL: fetch JD text, then run the paste pipeline on it."""
    import uuid

    form = dict(await request.form())
    fetched = fetch_url_text(form.get("url", ""))
    if not fetched["ok"]:
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE",
                                           "form_error": fetched["error"]})
    data = verify_paste(fetched["text"])
    if "card" not in data:
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE",
                                           "form_error": "Could not judge that page — paste the text instead."})
    data["card"]["source_url"] = fetched["final_url"]
    try:
        data["run_id"] = store.save_run("posting URL", fetched["final_url"][:80], data["mode"], [data["card"]],
            {"kind": "verify", "brain": data.get("brain", ""), "spent": data.get("spent", 0), "trace": data.get("trace", [])})
    except Exception:
        data["run_id"] = None
    data["thread_id"] = uuid.uuid4().hex[:8]
    data["thread"] = []
    data["idx"] = 0
    return templates.TemplateResponse(request, "verdict.html", data)


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    return templates.TemplateResponse(request, "profile.html",
                                      {"profile": store.get_profile(),
                                       "mode": "LIVE" if live_mode() else "FIXTURE"})


@app.post("/profile", response_class=HTMLResponse)
async def profile_upload(request: Request):
    form = dict(await request.form())
    up = form.get("resume")
    data = {"profile": store.get_profile(), "mode": "LIVE" if live_mode() else "FIXTURE"}
    if up is None or not hasattr(up, "read"):
        data["form_error"] = "Choose a PDF file first."
        return templates.TemplateResponse(request, "profile.html", data)
    raw = await up.read()
    parsed = resume.parse_pdf(raw)
    if not parsed["ok"]:
        data["form_error"] = parsed["error"]
        return templates.TemplateResponse(request, "profile.html", data)
    found = resume.extract_skills(parsed["text"])
    store.save_profile(getattr(up, "filename", "resume.pdf") or "resume.pdf",
                       found["skills"], found["level"], parsed["text"])
    data["profile"] = store.get_profile()
    data["saved"] = True
    return templates.TemplateResponse(request, "profile.html", data)


@app.post("/api/chat")
async def chat_api(request: Request):
    body = await request.json() or {}
    try:
        run_id, idx = int(body.get("run_id", 0)), int(body.get("idx", 0))
    except ValueError:
        return JSONResponse({"error": "bad run_id/idx"}, status_code=400)
    run = store.get_run(run_id)
    if not run or not (0 <= idx < len(run["cards"])):
        return JSONResponse({"error": "snapshot not found"}, status_code=404)
    return JSONResponse(chat_answer(body.get("thread_id") or "t0", run["cards"][idx],
                                    body.get("question", "")))


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    return templates.TemplateResponse(request, "history.html", {"runs": store.list_runs()})


@app.get("/history/{rid}", response_class=HTMLResponse)
def run_detail(request: Request, rid: int):
    """Reopen a saved check in the SAME full UI (results or verdict + chat)."""
    import uuid as _uuid

    run = store.get_run(rid)
    if not run:
        return templates.TemplateResponse(request, "history.html", {"runs": store.list_runs(), "missing": rid})
    meta = run.get("meta", {})
    cards = run["cards"]
    if meta.get("kind") == "verify" and len(cards) == 1:
        card = cards[0]
        return templates.TemplateResponse(request, "verdict.html",
                                          {"mode": run["mode"], "card": card, "errors": [],
                                           "trace": meta.get("trace", []), "spent": meta.get("spent", 0),
                                           "budget": 3, "brain": meta.get("brain", ""),
                                           "run_id": rid, "idx": 0,
                                           "thread_id": _uuid.uuid4().hex[:8], "thread": []})
    return templates.TemplateResponse(request, "results.html",
                                      {"mode": run["mode"], "role": run["role"], "location": run["location"],
                                       "cards": cards, "errors": [], "summary": summarize(cards),
                                       "run_id": rid, "hide_risky": False, "hide_senior": False,
                                       "brain": meta.get("brain", ""), "spent": meta.get("spent", 0),
                                       "budget": 7, "trace": meta.get("trace", [])})


# ---------------- live progress streaming (SSE) ----------------
# Slow runs (>10s on live data) get staged progress + skeletons, per NN/g
# guidance: the checklist ticks on REAL agent milestones, never fake timers.
# Old /search + /verify routes keep working untouched (no-JS fallback).

RUNS: dict[str, dict] = {}
MAX_RUNS = 20


def _start_run(kind: str, **kwargs) -> str:
    import queue
    import threading
    import uuid

    token = uuid.uuid4().hex[:10]
    q: queue.Queue = queue.Queue()
    RUNS[token] = {"kind": kind, "events": [], "result": None, "error": None, "queue": q}
    while len(RUNS) > MAX_RUNS:
        RUNS.pop(next(iter(RUNS)))

    def emit(kind_, detail=""):
        q.put({"kind": kind_, "detail": str(detail)[:120]})

    def work():
        try:
            if kind == "search":
                data = run_agent(kwargs["role"], kwargs["location"], emit=emit)
                enrich(data["cards"])
                try:
                    data["run_id"] = store.save_run(kwargs["role"], kwargs["location"],
                                                    data["mode"], data["cards"],
                                                    {"kind": "search", "brain": data.get("brain", ""),
                                                     "spent": data.get("spent", 0), "trace": data.get("trace", [])})
                except Exception:
                    data["run_id"] = None
                data["summary"] = summarize(data["cards"])
            else:
                data = verify_paste(kwargs["text"], emit=emit)
                if "card" in data:
                    _enrich_paste_card(data["card"])
                    try:
                        data["run_id"] = store.save_run("pasted message", "—", data["mode"], [data["card"]],
                                                        {"kind": "verify", "brain": data.get("brain", ""),
                                                         "spent": data.get("spent", 0), "trace": data.get("trace", [])})
                    except Exception:
                        data["run_id"] = None
            RUNS[token]["result"] = data
            q.put({"kind": "done", "detail": token})
        except Exception as e:  # noqa: BLE001 — background errors must surface, not vanish
            RUNS[token]["error"] = f"{type(e).__name__}: {str(e)[:150]}"
            q.put({"kind": "error", "detail": RUNS[token]["error"]})

    threading.Thread(target=work, daemon=True).start()
    return token


def _enrich_paste_card(card: dict) -> None:
    from urllib.parse import quote_plus

    card["prep_role"] = interview.role_for(card.get("description", ""))
    card["prep"] = interview.TOPICS[card["prep_role"]][:3]
    try:
        profile = store.get_profile()
    except Exception:
        profile = None
    card["match"] = resume.match(card.get("description", ""), profile) if profile else None


@app.post("/go/search", response_class=HTMLResponse)
async def go_search(request: Request):
    form = dict(await request.form())
    role = (form.get("role") or "python").strip()[:80] or "python"
    location = (form.get("location") or "Bengaluru").strip()[:80] or "Bengaluru"
    token = _start_run("search", role=role, location=location)
    return templates.TemplateResponse(request, "progress.html",
                                      {"token": token, "title": f"{role} in {location}", "kind": "search"})


@app.post("/go/verify", response_class=HTMLResponse)
async def go_verify(request: Request):
    form = dict(await request.form())
    text = (form.get("text") or "").strip()
    if not text:
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE"})
    token = _start_run("verify", text=text[:8000])
    return templates.TemplateResponse(request, "progress.html",
                                      {"token": token, "title": "your message", "kind": "verify"})


@app.get("/stream/{token}")
async def stream_run(token: str):
    from fastapi.responses import StreamingResponse

    run = RUNS.get(token)
    if not run:
        async def empty():
            yield 'event: error\ndata: {"detail": "unknown run"}\n\n'
        return StreamingResponse(empty(), media_type="text/event-stream")

    async def gen():
        import asyncio
        import json as _json

        q = run["queue"]
        while True:
            try:
                ev = await asyncio.to_thread(q.get, True, 25)
            except Exception:
                yield ": ping\n\n"
                continue
            run["events"].append(ev)
            yield f"event: {ev['kind']}\ndata: {_json.dumps(ev)}\n\n"
            if ev["kind"] in ("done", "error"):
                break

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/view/{token}", response_class=HTMLResponse)
async def view_run(request: Request, token: str):
    import uuid as _uuid

    run = RUNS.get(token)
    if not run or not run.get("result"):
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE",
                                           "form_error": "That run isn't ready — try again."})
    data = run["result"]
    if run["kind"] == "search":
        data = dict(data)
        data["hide_risky"] = False
        data["hide_senior"] = False
        return templates.TemplateResponse(request, "results.html", data)
    data = dict(data)
    data["thread_id"] = _uuid.uuid4().hex[:8]
    data["thread"] = []
    data["idx"] = 0
    return templates.TemplateResponse(request, "verdict.html", data)
