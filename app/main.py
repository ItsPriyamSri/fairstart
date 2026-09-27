"""FastAPI app: fresher job search -> dedup -> trust cards with provenance."""
import os
import uuid
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, interview, resume, scoring, store
from .agent import chat_answer, fetch_url_text, run_agent, verify_paste

app = FastAPI(title="FairStart")
BASE = os.path.dirname(os.path.dirname(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
if os.path.isdir(os.path.join(BASE, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.middleware("http")
async def visitor_cookie(request: Request, call_next):
    """Anonymous per-browser ID: every visitor gets a fresh history, no login.
    Judges land on an empty page; your prep stays yours."""
    vid = request.cookies.get("fs_vid") or ""
    new = False
    if not vid or len(vid) > 64 or not vid.replace("_", "").replace("-", "").isalnum():
        vid = uuid.uuid4().hex[:16]
        new = True
    request.state.visitor = vid
    resp = await call_next(request)
    if new:
        resp.set_cookie("fs_vid", vid, max_age=31536000, httponly=True, samesite="lax")
    return resp


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


def run_pipeline(role: str, location: str, visitor: str = "anon") -> dict:
    """One agentic run: plan -> act (SerpApi tools) -> synthesize -> snapshot."""
    data = run_agent(role, location)
    enrich(data["cards"], visitor)
    try:
        run_id = store.save_run(role, location, data["mode"], data["cards"],
            {"kind": "search", "brain": data.get("brain", ""), "spent": data.get("spent", 0), "trace": data.get("trace", [])},
            visitor=visitor)
    except Exception:
        run_id = None
    data["summary"] = summarize(data["cards"])
    data["run_id"] = run_id
    return data


def enrich(cards: list[dict], visitor: str = "anon") -> None:
    """Resume Match% + interview prep topics on each card (all local, free)."""
    profile = None
    try:
        profile = store.get_profile(visitor)
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
    data = run_pipeline(role.strip() or "python", location.strip() or "Bengaluru",
                        visitor=request.state.visitor)
    data["cards"] = apply_filters(data["cards"], hide_risky, hide_senior)
    data["summary"] = summarize(data["cards"])
    data["hide_risky"] = hide_risky
    data["hide_senior"] = hide_senior
    return templates.TemplateResponse(request, "results.html", data)


@app.get("/api/search")
def search_api(
    request: Request,
    role: str = Query("python", max_length=80),
    location: str = Query("Bengaluru", max_length=80),
):
    return JSONResponse(run_pipeline(role.strip() or "python", location.strip() or "Bengaluru",
                                      visitor=request.state.visitor))


@app.get("/export.csv")
def export_csv(request: Request, run_id: int = Query(0)):
    import csv
    import io

    run = store.get_run(run_id, request.state.visitor)
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
    _enrich_paste_card(card, request.state.visitor)
    try:
        data["run_id"] = store.save_run("pasted message", "—", data["mode"], [data["card"]],
            {"kind": "verify", "brain": data.get("brain", ""), "spent": data.get("spent", 0), "trace": data.get("trace", [])},
            visitor=request.state.visitor)
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
    run = store.get_run(run_id, request.state.visitor)
    if not run or not (0 <= idx < len(run["cards"])):
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE"})
    thread_id = form.get("thread_id") or "t0"
    data = chat_answer(f"{request.state.visitor}:{thread_id}", run["cards"][idx], form.get("question", ""))
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
    _enrich_paste_card(data["card"], request.state.visitor)
    try:
        data["run_id"] = store.save_run("posting URL", fetched["final_url"][:80], data["mode"], [data["card"]],
            {"kind": "verify", "brain": data.get("brain", ""), "spent": data.get("spent", 0), "trace": data.get("trace", [])},
            visitor=request.state.visitor)
    except Exception:
        data["run_id"] = None
    data["thread_id"] = uuid.uuid4().hex[:8]
    data["thread"] = []
    data["idx"] = 0
    return templates.TemplateResponse(request, "verdict.html", data)


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    return templates.TemplateResponse(request, "profile.html",
                                      {"profile": store.get_profile(request.state.visitor),
                                       "mode": "LIVE" if live_mode() else "FIXTURE"})


@app.post("/profile", response_class=HTMLResponse)
async def profile_upload(request: Request):
    form = dict(await request.form())
    up = form.get("resume")
    data = {"profile": store.get_profile(request.state.visitor), "mode": "LIVE" if live_mode() else "FIXTURE"}
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
                       found["skills"], found["level"], parsed["text"],
                       visitor=request.state.visitor)
    data["profile"] = store.get_profile(request.state.visitor)
    data["saved"] = True
    return templates.TemplateResponse(request, "profile.html", data)


@app.post("/api/advance")
async def api_advance(request: Request):
    """One agent step on client-carried state. Stateless: any instance can
    continue any run. Returns {state, events, done}."""
    from app.agent import new_search_state, new_verify_state, step

    body = await request.json() or {}
    st = body.get("state") or {}
    try:
        if not st or st.get("kind") == "search":
            if not st:
                st = new_search_state((body.get("role") or "python")[:80],
                                      (body.get("location") or "Bengaluru")[:80])
            events = step(st)
        elif st.get("kind") == "verify":
            if "extracted" not in st and "text" not in st:
                st = new_verify_state(body.get("text", ""))
                if not (st.get("text") or "").strip():
                    return JSONResponse({"error": "empty message"}, status_code=400)
            events = step(st)
        else:
            return JSONResponse({"error": "unknown run kind"}, status_code=400)
    except Exception as e:  # noqa: BLE001 — a stuck run must explain, not hang
        return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:150]}"}, status_code=500)
    return JSONResponse({"state": st, "events": events, "done": bool(st.get("done"))})


@app.post("/render/search", response_class=HTMLResponse)
async def render_search(request: Request):
    """Render finished search state to the full results page (saves snapshot)."""
    import uuid as _uuid

    body = await request.json() or {}
    st = body.get("state") or {}
    result = st.get("result") or {}
    cards = result.get("cards", [])
    enrich(cards, request.state.visitor)
    try:
        run_id = store.save_run(st.get("role", ""), st.get("location", ""), st.get("mode", ""),
                                cards, {"kind": "search", "brain": result.get("brain", ""),
                                        "spent": result.get("spent", 0), "trace": result.get("trace", [])},
                                visitor=request.state.visitor)
    except Exception:
        run_id = None
    return templates.TemplateResponse(request, "results.html",
                                      {"mode": st.get("mode", ""), "role": st.get("role", ""),
                                       "location": st.get("location", ""), "cards": cards,
                                       "errors": result.get("errors", []),
                                       "summary": summarize(cards), "run_id": run_id,
                                       "hide_risky": False, "hide_senior": False,
                                       "brain": result.get("brain", ""),
                                       "spent": result.get("spent", 0),
                                       "budget": st.get("budget", 7),
                                       "trace": result.get("trace", [])})


@app.post("/render/verify", response_class=HTMLResponse)
async def render_verify(request: Request):
    """Render a finished paste verdict to the full verdict page (saves snapshot)."""
    import uuid as _uuid

    body = await request.json() or {}
    st = body.get("state") or {}
    result = st.get("result") or {}
    if "card" not in result and "cards" not in result:
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE",
                                           "form_error": "That run didn't finish — try again."})
    card = (result.get("cards") or [result.get("card")])[0] if result.get("cards") else result["card"]
    _enrich_paste_card(card, request.state.visitor)
    try:
        run_id = store.save_run("pasted message", "—", st.get("mode", ""), [card],
                                {"kind": "verify", "brain": result.get("brain", ""),
                                 "spent": result.get("spent", 0), "trace": result.get("trace", [])},
                                visitor=request.state.visitor)
    except Exception:
        run_id = None
    return templates.TemplateResponse(request, "verdict.html",
                                      {"mode": st.get("mode", ""), "card": card,
                                       "errors": result.get("errors", []),
                                       "trace": result.get("trace", []),
                                       "spent": result.get("spent", 0),
                                       "budget": st.get("budget", 3),
                                       "brain": result.get("brain", ""),
                                       "run_id": run_id, "idx": 0,
                                       "thread_id": _uuid.uuid4().hex[:8], "thread": []})
@app.post("/api/chat")
async def chat_api(request: Request):
    body = await request.json() or {}
    try:
        run_id, idx = int(body.get("run_id", 0)), int(body.get("idx", 0))
    except ValueError:
        return JSONResponse({"error": "bad run_id/idx"}, status_code=400)
    run = store.get_run(run_id, request.state.visitor)
    if not run or not (0 <= idx < len(run["cards"])):
        return JSONResponse({"error": "snapshot not found"}, status_code=404)
    return JSONResponse(chat_answer(f"{request.state.visitor}:{body.get('thread_id') or 't0'}",
                                    run["cards"][idx], body.get("question", "")))


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    return templates.TemplateResponse(request, "history.html", {"runs": store.list_runs(visitor=request.state.visitor)})


@app.get("/history/{rid}", response_class=HTMLResponse)
def run_detail(request: Request, rid: int):
    """Reopen a saved check in the SAME full UI (results or verdict + chat)."""
    import uuid as _uuid

    run = store.get_run(rid, request.state.visitor)
    if not run:
        return templates.TemplateResponse(request, "history.html", {"runs": store.list_runs(visitor=request.state.visitor), "missing": rid})
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


# ---------------- stateless progress runs ----------------
# The client drives the agent one step per HTTP call (/api/advance), carrying
# state itself. Works on ANY serverless instance: no background threads, no
# shared memory, no sticky sessions, no hangs. (An earlier SSE design died
# here — instance A's worker was invisible to instance B's stream.)
# Old /search + /verify routes keep working untouched (no-JS fallback).


def _enrich_paste_card(card: dict, visitor: str = "anon") -> None:
    card["prep_role"] = interview.role_for(card.get("description", ""))
    card["prep"] = interview.TOPICS[card["prep_role"]][:3]
    try:
        profile = store.get_profile(visitor)
    except Exception:
        profile = None
    card["match"] = resume.match(card.get("description", ""), profile) if profile else None


@app.post("/go/search", response_class=HTMLResponse)
async def go_search(request: Request):
    form = dict(await request.form())
    role = (form.get("role") or "python").strip()[:80] or "python"
    location = (form.get("location") or "Bengaluru").strip()[:80] or "Bengaluru"
    return templates.TemplateResponse(request, "progress.html",
                                      {"title": f"{role} in {location}", "kind": "search",
                                       "role": role, "location": location, "text": ""})


@app.post("/go/verify", response_class=HTMLResponse)
async def go_verify(request: Request):
    form = dict(await request.form())
    text = (form.get("text") or "").strip()
    if not text:
        return templates.TemplateResponse(request, "index.html",
                                          {"mode": "LIVE" if live_mode() else "FIXTURE"})
    return templates.TemplateResponse(request, "progress.html",
                                      {"title": "your message", "kind": "verify",
                                       "role": "", "location": "", "text": text[:8000]})
