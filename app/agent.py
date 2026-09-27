"""Agentic verification loop: plan -> act (SerpApi tools) -> synthesize.
The agent decides WHICH verification steps to run within a hard credit
budget, then turns retrieved evidence into scored verdicts. Two brains:

- DeterministicBackend (default, no key): scripted policy, fully offline.
- GeminiBackend (opt-in via GEMINI_API_KEY): LLM plans + reasons over the
  same tools and evidence. Every citation is validated against retrieved
  evidence IDs; failures fall back to the deterministic step and are shown
  in the trace. The product NEVER needs the LLM to function.

Tool budget: 1 jobs_search + fan-out verify per company (news+presence+forums),
capped by MAX_VERIFY_COMPANIES. Fixture calls cost 0 SerpApi credits.
Safe space first: verdicts speak like a protective senior — blame the scammer,
never the student — and every claim stays cited or is labeled as guidance.
"""
import json
import re

from . import claims as claimlib, coach, config, llm, scoring
from . import serpapi_client as api

# ---------------- tools ----------------

def _fixture_mode() -> bool:
    return not bool(config.SERPAPI_API_KEY)


def tool_jobs_search(query: str, location: str, ctx: dict):
    """Primary evidence: fresher postings. Cost: 1 SerpApi credit (0 in fixture)."""
    if _fixture_mode():
        raw = api.load_fixture("jobs_bengaluru_python.json")
        spent = 0
    else:
        raw = api.jobs(query + " fresher", location)
        spent = 1
    jobs = [scoring.normalize_job(j) for j in raw.get("jobs_results", [])]
    jobs = scoring.dedupe(jobs)
    ev = []
    for j in jobs:
        ctx["eid"] += 1
        eid = f"E{ctx['eid']}"
        j["_eid"] = eid
        ev.append({"id": eid, "kind": "posting",
                   "text": f"{j['title']} @ {j['company']} ({j['location']}, via {j['via']}, {j.get('posted_at') or 'date unknown'}): {j['description'][:600]}"})
    return {"jobs": jobs, "evidence": ev, "spent": spent}


def tool_company_news(company: str, ctx: dict):
    """Legitimacy signal: scam/fraud news hits. Cost: 1 (0 in fixture)."""
    if _fixture_mode():
        raw = api.load_fixture("news_hcl.json") if "hcl" in company.lower() else {"news_results": []}
        spent = 0
    else:
        raw = api.company_news(company, ctx)
        spent = 1
    items = raw.get("news_results", [])[:3]
    ev = []
    for n in items:
        ctx["eid"] += 1
        eid = f"E{ctx['eid']}"
        ev.append({"id": eid, "kind": "news",
                   "text": f"{n.get('title','')} ({(n.get('source') or {}).get('name','?')}): {n.get('link','')}"})
    return {"news": items, "evidence": ev, "spent": spent}


def tool_company_presence(company: str, ctx: dict):
    """Legitimacy signal: official web presence. Cost: 1 (0 in fixture)."""
    if _fixture_mode():
        raw = api.load_fixture("presence_nimbuspark.json") if "nimbuspark" in company.lower() else {"organic_results": []}
        spent = 0
    else:
        raw = api.company_presence(company, ctx)
        spent = 1
    items = raw.get("organic_results", [])[:3]
    ev = []
    for o in items:
        ctx["eid"] += 1
        eid = f"E{ctx['eid']}"
        ev.append({"id": eid, "kind": "presence",
                   "text": f"{o.get('title','')}: {o.get('link','')}"})
    return {"presence": items, "evidence": ev, "spent": spent}


def tool_forums_search(company: str, ctx: dict):
    """Victim threads: Reddit/forum scam discussions. Cost: 1 (0 in fixture)."""
    if _fixture_mode():
        low = company.lower()
        raw = api.load_fixture("forums_labmentix.json") if ("labmentix" in low or "codespark" in low or "hcl" in low) else {"organic_results": []}
        spent = 0
    else:
        raw = api.forums(company, ctx)
        spent = 1
    items = raw.get("organic_results", [])[:3]
    ev = []
    for o in items:
        ctx["eid"] += 1
        eid = f"E{ctx['eid']}"
        ev.append({"id": eid, "kind": "forums",
                   "text": f"{o.get('title','')} ({o.get('source','forum')}): {o.get('snippet','')[:200]} {o.get('link','')}"})
    return {"forums": items, "evidence": ev, "spent": spent}


TOOLS = {"jobs_search": tool_jobs_search, "company_news": tool_company_news,
         "company_presence": tool_company_presence, "forums_search": tool_forums_search}

_TOOL_LABELS = {"jobs_search": "job listings", "company_news": "news",
                "company_presence": "company presence", "forums_search": "community discussions"}


def _tool_label(name: str) -> str:
    return _TOOL_LABELS.get(name, "verification")

VERIFY_FANOUT = ("company_news", "company_presence", "forums_search")


def run_fanout(company: str, ctx: dict) -> dict:
    """Independent verification calls run concurrently (same credits, faster).

    Each thread gets a private counter; IDs are renumbered sequentially at
    merge so [E#] citations stay clean. Exceptions become error results,
    never silent — the loop records them in the trace.
    """
    from concurrent.futures import ThreadPoolExecutor

    out: dict = {"evidence": [], "spent": 0, "results": {}}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(TOOLS[t], company, {"eid": 0, "fast": True}): t for t in VERIFY_FANOUT}
        for f, t in futs.items():
            try:
                r = f.result()
            except Exception as e:
                r = {"error": f"{type(e).__name__}: {str(e)[:100]}",
                     "evidence": [], "spent": 0}
            out["results"][t] = r
            out["evidence"].extend(r.get("evidence", []))
            out["spent"] += r.get("spent", 0)
    for e in out["evidence"]:
        ctx["eid"] += 1
        e["id"] = f"E{ctx['eid']}"
    return out


def redact(args: dict) -> dict:
    return {k: ("<redacted>" if "key" in k.lower() else v) for k, v in args.items()}

# ---------------- structured-output schemas ----------------
# Gemini validates these server-side (responseSchema): no markdown, no drift.

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "job": {"type": "integer"},
                    "score": {"type": "integer"},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["job", "score", "reasons"],
            },
        }
    },
    "required": ["verdicts"],
}

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "string"},
        "role": {"type": "string"},
        "stipend": {"type": "string"},
        "fee_mentioned": {"type": "boolean"},
        "guarantee_mentioned": {"type": "boolean"},
    },
}

# ---------------- backends (the brain) ----------------

class DeterministicBackend:
    """Scripted policy: jobs first, then fan-out verify per new company."""

    name = "deterministic"

    def next_action(self, goal: dict, trace: list, state: dict):
        if not state.get("jobs_done"):
            return {"tool": "jobs_search",
                    "args": {"query": goal["role"], "location": goal["location"]}}
        for c in state.get("companies", []):
            if c not in state.get("verified", set()):
                return {"fanout": {"company": c}}
        return {"finish": True}

    def synthesize(self, jobs: list, evidence: list, job_ev: dict) -> list[dict]:
        """Signal-based verdicts with evidence citations attached per reason."""
        med = scoring.median_lpa(jobs)
        out = []
        for i, j in enumerate(jobs):
            ev = job_ev.get(i, {"news": 0, "forums": 0, "presence": False})
            s = scoring.score_job(j, ev["news"], ev["presence"], set_median=med)
            kinds = ev.get("by_kind", {})
            if ev.get("forums"):
                s["score"] = min(100, s["score"] + min(15, ev["forums"] * 5))
                s["reasons"].append(f"{ev['forums']} forum thread(s) discussing scams under this name — read before applying.")
            kinds = ev.get("by_kind", {})
            post = " ".join(f"[{e}]" for e in kinds.get("posting", [])[:1])
            news = " ".join(f"[{e}]" for e in (kinds.get("news", []) + kinds.get("forums", []))[:1])
            pres = " ".join(f"[{e}]" for e in kinds.get("presence", [])[:1])
            cited = []
            for r in s["reasons"]:
                tag = news if ("news hit" in r or "forum thread" in r) else pres if "web presence" in r else post
                cited.append(f"{r} {tag}".strip())
            out.append({"job": i, "score": s["score"], "reasons": cited})
        return out


class GeminiBackend(DeterministicBackend):
    """LLM brain over the same tools. Any failure -> deterministic step."""

    name = "gemini"
    model = config.GEMINI_MODEL

    def _call(self, prompt: str, schema: dict | None = None, max_tokens: int = 2048) -> str:
        import httpx

        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"
               f":generateContent?key={config.GEMINI_API_KEY}")
        gen: dict = {"temperature": 0.2, "maxOutputTokens": max_tokens}
        if schema is not None:  # structured output: schema-validated JSON, no markdown
            gen["responseMimeType"] = "application/json"
            gen["responseSchema"] = schema
        r = httpx.post(url, json={"contents": [{"parts": [{"text": prompt}]}],
                                  "generationConfig": gen},
                       timeout=20)
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    @staticmethod
    def _json(text: str) -> dict | None:
        try:
            start = text.index("{")
            return json.loads(text[start:text.rindex("}") + 1])
        except Exception:
            return None

    # NOTE: planning is intentionally deterministic (verify each discovered
    # company in order). An LLM planner added ~25s per run for zero better
    # decisions — the model's judgment belongs in synthesize, where evidence
    # actually needs reasoning. Custom backends may still override this.
    def next_action(self, goal: dict, trace: list, state: dict):
        return super().next_action(goal, trace, state)

    def synthesize(self, jobs: list, evidence: list, job_ev: dict) -> list[dict]:
        if not config.GEMINI_API_KEY:
            return super().synthesize(jobs, evidence, job_ev)
        med = scoring.median_lpa(jobs)
        bundle = []
        for i, j in enumerate(jobs):
            bundle.append({"job": i, "title": j["title"], "company": j["company"],
                           "location": j["location"], "via": j["via"],
                           "posted": j.get("posted_at"), "salary": j.get("salary"),
                           "evidence_ids": job_ev.get(i, {}).get("ids", []),
                           "fee_match": bool(scoring.FEE_PAT.search(j["title"] + "\n" + j["description"])),
                           "gmail_match": bool(scoring.GMAIL_PAT.search(j["title"] + "\n" + j["description"])),
                           "set_median_lpa": med})
        prompt = (
            "You score fresher job postings for scam risk. EVIDENCE (cite ONLY these IDs, format [E#]):\n"
            + json.dumps(evidence) + "\nJOBS:\n" + json.dumps(bundle)
            + "\nRed flags: fee/challan/UPI language, WhatsApp-only apply, Gmail contact, salary far above set median "
            "for freshers, stale date, missing company/apply link, mass reposts, pay-for-certificate plans. "
            "Write each reason in a warm senior-guide voice — plain words, no jargon, blame the scammer never the student — "
            "while keeping the [E#] citation. "
            "Before finalizing, self-check each verdict: does the score match its own reasons (damning reasons + low score = wrong)? "
            "Drop any verdict you cannot support. "
            "Reply with the JSON the schema requires. "
            "Every reason MUST cite at least one of that job's evidence_ids.")
        try:
            parsed = self._json(self._call(prompt, VERDICT_SCHEMA, max_tokens=1400))
            if parsed and isinstance(parsed.get("verdicts"), list) and parsed["verdicts"]:
                return parsed["verdicts"]
        except Exception:
            pass
        return super().synthesize(jobs, evidence, job_ev)

# ---------------- citation validator ----------------

def validate_verdicts(verdicts: list[dict], jobs: list, job_ev: dict) -> tuple[list[dict], int]:
    """Clamp scores, enforce per-job citation grounding. Returns (verdicts, corrections)."""
    det = DeterministicBackend()
    det_v = {v["job"]: v for v in det.synthesize(jobs, [], job_ev)}
    fixed, corrections = [], 0
    for v in verdicts:
        i = v.get("job")
        if not isinstance(i, int) or not (0 <= i < len(jobs)):
            corrections += 1
            continue
        ok_reasons = [r for r in (v.get("reasons") or [])
                      if any(f"E{e}" in r for e in job_ev.get(i, {}).get("nums", []))]
        if not ok_reasons:
            corrections += 1
            v = det_v[i]
        else:
            try:
                v["score"] = max(0, min(100, int(v.get("score", 50))))
            except Exception:
                v["score"] = det_v[i]["score"]
                corrections += 1
            v["reasons"] = ok_reasons
        v["job"] = i
        fixed.append(v)
    # any job the LLM dropped gets a deterministic verdict (flagged)
    have = {v["job"] for v in fixed}
    for i in range(len(jobs)):
        if i not in have:
            corrections += 1
            fixed.append(det_v[i])
    return fixed, corrections

# ---------------- stateless steps (serverless-proof) ----------------
# Each step is one unit of work on a plain-JSON state dict. The client
# carries state between HTTP calls, so ANY instance can continue the run —
# no background threads, no shared memory, no sticky sessions. run_agent()
# and verify_paste() below simply drive these steps in-process (tests + local).

def new_search_state(role: str, location: str) -> dict:
    return {"kind": "search", "role": role, "location": location, "text": "",
            "mode": "LIVE" if config.SERPAPI_API_KEY else "FIXTURE (recorded, labeled)",
            "jobs": [], "evidence": [], "companies": [], "verified": [],
            "spent": 0, "calls": 0, "eid": 0, "errors": [], "trace": [],
            "budget": 1 + 3 * config.MAX_VERIFY_COMPANIES, "done": False, "result": None}


def new_verify_state(text: str) -> dict:
    return {"kind": "verify", "role": "", "location": "", "text": (text or "")[:8000],
            "mode": "LIVE" if config.SERPAPI_API_KEY else "FIXTURE (recorded, labeled)",
            "jobs": [], "evidence": [], "companies": [], "verified": [],
            "spent": 0, "calls": 0, "eid": 0, "errors": [], "trace": [],
            "budget": 3, "done": False, "result": None, "claims": None, "fetched_from": []}


def _backend(backend=None):
    return backend or (GeminiBackend() if config.GEMINI_API_KEY else DeterministicBackend())


def _pending_company(st: dict) -> str:
    if st.get("calls", 0) + 3 > st["budget"] + 2 or st.get("spent", 0) + 3 > st["budget"]:
        return ""
    for c in st.get("companies", []):
        if c not in st.get("verified", []):
            return c
    return ""


def step(st: dict, backend=None) -> list:
    """Run ONE unit of work, mutate st, return new trace events. Sets st['done']."""
    backend = _backend(backend)
    before = len(st["trace"])
    ctx = {"eid": st.get("eid", 0)}
    if st["kind"] == "verify" and not st.get("extracted"):
        _verify_extract_step(st, ctx, backend)
    elif not st.get("jobs_done") and st["kind"] == "search":
        _jobs_step(st, ctx, {"role": st.get("role", ""), "location": st.get("location", "")})
    else:
        company = ""
        if st["kind"] == "verify":
            cl = st.get("claims", {})
            names = (cl.get("companies", []) + ([cl["brand_hit"]] if cl.get("brand_hit") else []))[:1]
            if names and names[0] not in st.get("verified", []) and st.get("calls", 0) + 3 <= st["budget"] + 2 and st.get("spent", 0) + 3 <= st["budget"]:
                company = names[0]
        else:
            company = _pending_company(st)
        if company:
            _fanout_step(st, ctx, company)
        elif st["kind"] == "verify":
            _verify_synthesize_step(st, backend)
        else:
            _synthesize_step(st, backend)
    st["eid"] = ctx["eid"]
    return st["trace"][before:]


def _jobs_step(st: dict, ctx: dict, goal: dict):
    try:
        res = tool_jobs_search(goal["role"], goal["location"], ctx)
        st["spent"] += res.get("spent", 0)
        st["evidence"].extend(res.get("evidence", []))
        st["jobs"] = res["jobs"]
        for j in res["jobs"]:
            if j["company"] and j["company"] not in st["companies"]:
                st["companies"].append(j["company"])
        st["companies"] = st["companies"][:config.MAX_VERIFY_COMPANIES]
        _rec(st["trace"], None, {"kind": "tool", "tool": "jobs_search",
                                 "args": {"query": goal["role"], "location": goal["location"]},
                                 "ok": True, "credits": res.get("spent", 0)})
    except Exception as e:
        _rec(st["trace"], None, {"kind": "tool", "tool": "jobs_search", "ok": False,
                                 "note": f"{type(e).__name__}"})
        st["errors"].append("Job listings didn't load — showing recorded samples instead.")
        raw = api.load_fixture("jobs_bengaluru_python.json")
        st["jobs"] = scoring.dedupe([scoring.normalize_job(j) for j in raw.get("jobs_results", [])])
        st["mode"] = "FIXTURE (recorded, labeled)"
    st["jobs_done"] = True
    st["calls"] = st.get("calls", 0) + 1


def _fanout_step(st: dict, ctx: dict, company: str):
    st["calls"] = st.get("calls", 0) + 3
    try:
        res = run_fanout(company, ctx)
        st["spent"] += res["spent"]
        st["evidence"].extend(res["evidence"])
        st["verified"].append(company)
        bad = [t for t, r in res["results"].items() if "error" in r]
        _rec(st["trace"], None, {"kind": "fanout", "tool": "news+presence+forums",
                                 "args": {"company": company}, "ok": not bad,
                                 "note": f"skipped: {bad}" if bad else "",
                                 "credits": res["spent"]})
        if bad:
            st["errors"].append(f"One check ({', '.join(bad)}) didn't load for {company} — verdict uses the checks that worked.")
    except Exception as e:
        _rec(st["trace"], None, {"kind": "fanout", "tool": "news+presence+forums",
                                 "args": {"company": company}, "ok": False,
                                 "note": f"{type(e).__name__}"})
        st["errors"].append(f"Couldn't reach live checks for {company} — judged on the listing text alone.")


def _job_ev_map(jobs: list, evidence: list) -> dict:
    job_ev = {}
    for i, j in enumerate(jobs):
        mine = [e for e in evidence if _ev_for_job(e, j, jobs)]
        by_kind: dict[str, list[str]] = {"posting": [], "news": [], "presence": [], "forums": []}
        for e in mine:
            by_kind.setdefault(e["kind"], []).append(e["id"])
        nums = set()
        for e in mine:
            m = re.search(r"E(\d+)", e["id"])
            if m:
                nums.add(int(m.group(1)))
        job_ev[i] = {"news": len(by_kind["news"]), "forums": len(by_kind["forums"]),
                     "presence": bool(by_kind["presence"]), "ids": [e["id"] for e in mine],
                     "nums": nums, "by_kind": by_kind}
    return job_ev


def _synthesize_step(st: dict, backend):
    from . import claims as _cl

    job_ev = _job_ev_map(st["jobs"], st["evidence"])
    try:
        verdicts = backend.synthesize(st["jobs"], st["evidence"], job_ev)
    except Exception:
        st["errors"].append("Brain hiccup — used the reliable fallback to finish your verdict.")
        verdicts = DeterministicBackend().synthesize(st["jobs"], st["evidence"], job_ev)
    verdicts, corrections = validate_verdicts(verdicts, st["jobs"], job_ev)
    if corrections:
        _rec(st["trace"], None, {"kind": "validate",
                                 "note": f"{corrections} verdict(s) failed citation check — deterministic fallback applied"})
    problems = critique(verdicts, st["jobs"], job_ev, backend)
    if problems:
        det_v = {v["job"]: v for v in DeterministicBackend().synthesize(st["jobs"], st["evidence"], job_ev)}
        swapped = 0
        for p in problems:
            i = p.get("job")
            if isinstance(i, int) and 0 <= i < len(verdicts):
                for k, v in enumerate(verdicts):
                    if v["job"] == i and v["reasons"] != det_v.get(i, {}).get("reasons"):
                        verdicts[k] = det_v[i]
                        swapped += 1
                        break
        _rec(st["trace"], None, {"kind": "reflect",
                                 "note": f"critic: {len(problems)} issue(s), {swapped} repaired"})
    _rec(st["trace"], None, {"kind": "synthesis",
                             "note": f"brain={backend.name}, verdicts={len(verdicts)}, corrections={corrections}"})
    cards = []
    for v in verdicts:
        j = st["jobs"][v["job"]]
        band = "green" if v["score"] <= 30 else "amber" if v["score"] <= 60 else "red"
        ev_news = [e for e in st["evidence"] if e["kind"] in ("news", "forums") and _ev_for_job(e, j, st["jobs"])]
        ev_pres = [e for e in st["evidence"] if e["kind"] == "presence" and _ev_for_job(e, j, st["jobs"])]
        cl = _cl.extract(f"{j['title']}\n{j['company']}\n{j['description']}")
        category = _cl.category_for(cl)
        if category == "clean" and band == "red":
            category = "scam"
        proof = bool(ev_pres)
        cards.append({**j, "score": v["score"], "band": band, "reasons": v["reasons"],
                      "label": _cl.label_for(v["score"], category, proof=proof),
                      "category": category, "claims": cl,
                      "coach": {"opener": coach.opener_for(category),
                                "cons": coach.cons_for(cl["cues"]),
                                "closer": coach.closer_for(category)},
                      "evidence": {"news": [_news_card(e["text"]) for e in ev_news],
                                   "presence": [_presence_card(e["text"]) for e in ev_pres]},
                      "summary": llm.grounded_bullets(v["reasons"])})
    cards.sort(key=lambda c: c["score"])
    st["result"] = {"cards": cards, "errors": st["errors"], "trace": st["trace"],
                    "spent": st["spent"], "brain": backend.name, "budget": st["budget"]}
    st["done"] = True


def _verify_extract_step(st: dict, ctx: dict, backend=None):
    from . import claims as _cl

    text = st.get("text", "")
    urls = re.findall(r"https?://[^\s)>\]]+", text)[:2]
    fetched_from = []
    for u in urls:
        got = fetch_url_text(u.rstrip(".,"))
        if got["ok"]:
            text = (text + "\n\n[Fetched page content]\n" + got["text"])[:8000]
            fetched_from.append(got["final_url"])
            _rec(st["trace"], None, {"kind": "tool", "tool": "fetch_url",
                                     "args": {"url": u[:60]}, "ok": True, "credits": 0})
        else:
            _rec(st["trace"], None, {"kind": "tool", "tool": "fetch_url",
                                     "args": {"url": u[:60]}, "ok": False, "note": got["error"]})
            st["errors"].append(f"Could not read {u[:60]}: {got['error']}")
    st["text"] = text
    st["fetched_from"] = fetched_from
    st["claims"] = _cl.extract(text)
    _rec(st["trace"], None, {"kind": "extract", "note": "claim extraction from pasted text"})
    if (not st["claims"]["companies"] and not st["claims"]["brand_hit"]
            and config.GEMINI_API_KEY and isinstance(backend, GeminiBackend)):
        try:
            parsed = GeminiBackend._json(backend._call(
                "Extract from this opportunity message as JSON: " + text[:1500], CLAIM_SCHEMA))
            if parsed and parsed.get("company"):
                st["claims"]["companies"] = [parsed["company"]]
        except Exception as e:
            _rec(st["trace"], None, {"kind": "extract",
                                     "note": f"LLM cross-check failed ({type(e).__name__}) — deterministic claims kept"})
    if not st["claims"]["companies"] and not st["claims"]["brand_hit"]:
        st["jobs"] = []
        st["companies"] = []
    else:
        st["jobs"] = []
        st["companies"] = []
    st["extracted"] = True


def _verify_synthesize_step(st: dict, backend):
    from . import claims as _cl

    cl = st["claims"]
    company = (cl["companies"] + [cl["brand_hit"]] if cl["brand_hit"] else cl["companies"])
    company = company[0] if company else ""
    news_items = [e for e in st["evidence"] if e["kind"] == "news"]
    forum_items = [e for e in st["evidence"] if e["kind"] == "forums"]
    pres_items = [e for e in st["evidence"] if e["kind"] == "presence"]
    job = {"title": "Pasted opportunity", "company": company, "location": "—", "via": "pasted message",
           "posted_at": None, "salary": " ".join(cl["money"][:2]), "schedule": "",
           "description": st["text"], "apply": [], "share_link": "", "job_id": "", "_dupes": 1}
    for i, e in enumerate(st["evidence"]):
        e["id"] = f"E{i + 1}"
    job_ev = {0: {"news": len(news_items), "forums": len(forum_items), "presence": bool(pres_items),
                  "ids": [e["id"] for e in st["evidence"]],
                  "nums": set(range(1, len(st["evidence"]) + 1)),
                  "by_kind": {"posting": [],
                              "news": [e["id"] for e in news_items],
                              "presence": [e["id"] for e in pres_items],
                              "forums": [e["id"] for e in forum_items]}}}
    s = scoring.score_paste(job, cl["cues"], news_hits=len(news_items),
                            has_presence=bool(pres_items), forum_hits=len(forum_items))
    category = _cl.category_for(cl)
    label = _cl.label_for(s["score"], category, proof=bool(pres_items))
    verdicts = [{"job": 0, "score": s["score"],
                 "reasons": [f"{r} [{job_ev[0]['ids'][0]}]" if job_ev[0]["ids"] else r for r in s["reasons"]]}]
    verdicts, corrections = validate_verdicts_paste(verdicts, job_ev)
    issues = critique(verdicts, [job], job_ev, backend)
    if issues:
        _rec(st["trace"], None, {"kind": "reflect",
                                 "note": f"critic flagged {len(issues)} issue(s)"})
    if corrections:
        _rec(st["trace"], None, {"kind": "validate", "note": f"{corrections} correction(s) applied"})
    _rec(st["trace"], None, {"kind": "synthesis",
                             "note": f"brain={backend.name}, category={category}, label={label}"})
    from urllib.parse import quote_plus

    from . import interview as _iv

    role_key = _iv.role_for(st["text"])
    search_role = {"python": "python", "web": "web developer", "frontend": "frontend",
                   "data": "data analyst", "java": "java"}.get(role_key, "fresher")
    ev_news = [e for e in st["evidence"] if e["kind"] in ("news", "forums")]
    ev_pres = [e for e in st["evidence"] if e["kind"] == "presence"]
    card = {**job, "score": s["score"],
            "band": "green" if s["score"] <= 30 else "amber" if s["score"] <= 60 else "red",
            "reasons": verdicts[0]["reasons"] if verdicts else s["reasons"],
            "label": label, "category": category, "claims": cl,
            "coach": {"opener": coach.opener_for(category),
                      "cons": coach.cons_for(cl["cues"]),
                      "closer": coach.closer_for(category)},
            "evidence": {"news": [_news_card(e["text"]) for e in ev_news],
                         "presence": [_presence_card(e["text"]) for e in ev_pres]},
            "summary": llm.grounded_bullets(verdicts[0]["reasons"] if verdicts else s["reasons"]),
            "next_steps": NEXT_STEPS,
            "source_url": st["fetched_from"][0] if st["fetched_from"] else "",
            "search_role": search_role,
            "search_link": f"/search?role={quote_plus(search_role)}&location=India"}
    st["result"] = {"card": card, "errors": st["errors"], "trace": st["trace"],
                    "spent": st["spent"], "brain": backend.name, "budget": st["budget"]}
    st["done"] = True


# ---------------- loop ----------------

def _rec(trace: list, emit, entry: dict) -> None:
    """Trace + optional live progress callback (SSE). Emit failures never break runs."""
    trace.append(entry)
    if emit:
        try:
            emit(entry.get("kind", "step"), entry.get("tool") or entry.get("note", ""))
        except Exception:
            pass


def _run_agent_legacy(role: str, location: str, backend=None, emit=None) -> dict:
    """emit(kind, note) fires on every real milestone for SSE progress streaming."""
    backend = backend or (GeminiBackend() if config.GEMINI_API_KEY else DeterministicBackend())
    budget = 1 + 3 * config.MAX_VERIFY_COMPANIES  # 1 jobs + fan-out(news+presence+forums) per company
    ctx, trace, evidence, spent = {"eid": 0}, [], [], 0
    state: dict = {"budget": budget, "spent": 0, "verified": set(), "steps": set()}
    goal = {"role": role, "location": location}
    jobs: list = []
    job_ev: dict = {}
    errors: list[str] = []
    mode = "LIVE" if config.SERPAPI_API_KEY else "FIXTURE (recorded, labeled)"

    for _ in range(budget + 1):
        if state.get("calls", 0) == 0 and not state.get("jobs_done"):
            # Deterministic first step: every planner opens with jobs_search —
            # skip one LLM round-trip (~5-8s) without changing behavior.
            action = {"tool": "jobs_search", "args": {"query": role, "location": location}}
        else:
            try:
                action = backend.next_action(goal, trace, state)
            except Exception as e:
                errors.append("Planner hiccup — used the safe default plan instead.")
                action = DeterministicBackend().next_action(goal, trace, state)
        if action.get("finish"):
            pending = [c for c in state.get("companies", []) if c not in state.get("verified", set())]
            if pending and state.get("calls", 0) + 3 <= budget + 2 and state["spent"] + 3 <= budget:
                # Guardrail: the planner may not declare victory with companies
                # unverified and budget unspent. Enforce the next fan-out.
                action = {"fanout": {"company": pending[0]}}
                _rec(trace, emit, {"kind": "plan", "note": f"planner stopped early — enforced verify: {pending[0]}"})
            else:
                _rec(trace, emit, {"kind": "plan", "note": "finish: evidence sufficient"})
                break
        if "fanout" in action:
            company = (action.get("fanout") or {}).get("company", "")
            if not company or state.get("calls", 0) + 3 > budget + 2 or state["spent"] + 3 > budget:
                _rec(trace, emit, {"kind": "deny", "tool": "fanout", "note": "budget exhausted — finishing"})
                break
            state["calls"] = state.get("calls", 0) + 3
            try:
                res = run_fanout(company, ctx)
                state["spent"] += res["spent"]
                spent += res["spent"]
                evidence.extend(res["evidence"])
                state["verified"].add(company)
                bad = [t for t, r in res["results"].items() if "error" in r]
                _rec(trace, emit, {"kind": "fanout", "tool": "news+presence+forums",
                              "args": {"company": company}, "ok": not bad,
                              "note": f"skipped: {bad}" if bad else "",
                              "credits": res["spent"]})
                if bad:
                    errors.append(f"One check ({", ".join(bad)}) didn't load for {company} — verdict uses the checks that worked.")
            except Exception as e:
                _rec(trace, emit, {"kind": "fanout", "tool": "news+presence+forums",
                              "args": {"company": company}, "ok": False,
                              "note": f"{type(e).__name__}"})
                errors.append(f"Couldn't reach live checks for {company} — judged on the listing text alone.")
            continue
        name, args = action.get("tool"), action.get("args", {})
        if name not in TOOLS or state.get("calls", 0) >= budget or state["spent"] + 1 > budget:
            _rec(trace, emit, {"kind": "deny", "tool": name, "note": "unknown tool or budget exhausted — finishing"})
            break
        state["calls"] = state.get("calls", 0) + 1
        try:
            res = TOOLS[name](**args, ctx=ctx) if name == "jobs_search" else TOOLS[name](args.get("company", ""), ctx)
            state["spent"] += res.get("spent", 0)
            spent += res.get("spent", 0)
            evidence.extend(res.get("evidence", []))
            if name == "jobs_search":
                jobs = res["jobs"]
                state["jobs_done"] = True
                for j in jobs:
                    if j["company"]:
                        state.setdefault("companies", [])
                        if j["company"] not in state["companies"]:
                            state["companies"].append(j["company"])
                state["companies"] = state.get("companies", [])[:config.MAX_VERIFY_COMPANIES]
            else:
                c = args.get("company", "")
                state["steps"].add(f"{c}:{'news' if name == 'company_news' else 'presence'}")
                if f"{c}:news" in state["steps"] and f"{c}:presence" in state["steps"]:
                    state["verified"].add(c)
            _rec(trace, emit, {"kind": "tool", "tool": name, "args": redact(args), "ok": True,
                          "credits": res.get("spent", 0)})
        except Exception as e:
            _rec(trace, emit, {"kind": "tool", "tool": name, "args": redact(args), "ok": False,
                          "note": f"{type(e).__name__}: {str(e)[:120]}"})
            errors.append(f"The {_tool_label(name)} check didn't load — continuing with what we have.")
            if name == "jobs_search":
                raw = api.load_fixture("jobs_bengaluru_python.json")
                jobs = [scoring.normalize_job(j) for j in raw.get("jobs_results", [])]
                jobs = scoring.dedupe(jobs)
                state["jobs_done"] = True
                mode = "FIXTURE (recorded, labeled)"

    for i, j in enumerate(jobs):
        mine = [e for e in evidence if _ev_for_job(e, j, jobs)]
        by_kind: dict[str, list[str]] = {"posting": [], "news": [], "presence": [], "forums": []}
        for e in mine:
            by_kind.setdefault(e["kind"], []).append(e["id"])
        nums = set()
        for e in mine:
            m = re.search(r"E(\d+)", e["id"])
            if m:
                nums.add(int(m.group(1)))
        news_n = len(by_kind["news"])
        forum_n = len(by_kind["forums"])
        pres = bool(by_kind["presence"])
        job_ev[i] = {"news": news_n, "forums": forum_n, "presence": pres,
                     "ids": [e["id"] for e in mine],
                     "nums": nums, "by_kind": by_kind}

    try:
        verdicts = backend.synthesize(jobs, evidence, job_ev)
    except Exception as e:
        errors.append("Brain hiccup — used the reliable fallback to finish your verdict.")
        verdicts = DeterministicBackend().synthesize(jobs, evidence, job_ev)
    verdicts, corrections = validate_verdicts(verdicts, jobs, job_ev)
    if corrections:
        _rec(trace, emit, {"kind": "validate", "note": f"{corrections} verdict(s) failed citation check — deterministic fallback applied"})
    problems = critique(verdicts, jobs, job_ev, backend)
    if problems:
        det_v = {v["job"]: v for v in DeterministicBackend().synthesize(jobs, evidence, job_ev)}
        swapped = 0
        for p in problems:
            i = p.get("job")
            if isinstance(i, int) and 0 <= i < len(verdicts):
                for k, v in enumerate(verdicts):
                    if v["job"] == i and v["reasons"] != det_v.get(i, {}).get("reasons"):
                        verdicts[k] = det_v[i]
                        swapped += 1
                        break
        _rec(trace, emit, {"kind": "reflect",
                      "note": f"critic: {len(problems)} issue(s), {swapped} verdict(s) repaired — " + "; ".join(x["problem"][:80] for x in problems[:2])})
    _rec(trace, emit, {"kind": "synthesis", "note": f"brain={backend.name}, verdicts={len(verdicts)}, corrections={corrections}"})

    cards = []
    for v in verdicts:
        j = jobs[v["job"]]
        band = "green" if v["score"] <= 30 else "amber" if v["score"] <= 60 else "red"
        ev_news = [e for e in evidence if e["kind"] in ("news", "forums") and _ev_for_job(e, j, jobs)]
        ev_pres = [e for e in evidence if e["kind"] == "presence" and _ev_for_job(e, j, jobs)]
        cl = claimlib.extract(f"{j['title']}\n{j['company']}\n{j['description']}")
        category = claimlib.category_for(cl)
        if category == "clean" and band == "red":
            category = "scam"  # evidence-backed high score, no named cue pattern
        proof = bool([e for e in evidence if e["kind"] == "presence" and _ev_for_job(e, j, jobs)])
        cards.append({**j, "score": v["score"], "band": band, "reasons": v["reasons"],
                      "label": claimlib.label_for(v["score"], category, proof=proof),
                      "category": category, "claims": cl,
                      "coach": {"opener": coach.opener_for(category),
                                "cons": coach.cons_for(cl["cues"]),
                                "closer": coach.closer_for(category)},
                      "evidence": {"news": [_news_card(e["text"]) for e in ev_news],
                                   "presence": [_presence_card(e["text"]) for e in ev_pres]},
                      "summary": llm.grounded_bullets(v["reasons"])})
    cards.sort(key=lambda c: c["score"])
    return {"mode": mode, "role": role, "location": location, "cards": cards,
            "errors": errors, "trace": trace, "spent": spent,
            "brain": backend.name, "budget": budget}


def _news_card(t: str) -> dict:
    link = t.rsplit("https://", 1)
    head = link[0]
    url = ("https://" + link[1]) if len(link) > 1 else ""
    if " (" in head and head.rstrip().endswith(")"):
        title, src = head.rsplit(" (", 1)
        src = src.rstrip(")")
    else:
        title, src = head.strip(), "?"
    return {"title": title, "link": url, "source": {"name": src}}


def _presence_card(t: str) -> dict:
    link = t.rsplit("https://", 1)
    title = link[0].rstrip(": ").strip()
    url = ("https://" + link[1]) if len(link) > 1 else ""
    return {"title": title, "link": url}


def _ev_for_job(e: dict, job: dict, jobs: list) -> bool:
    """Posting evidence belongs to its job; news/forums/presence belong to same company."""
    if e["kind"] == "posting":
        return e["id"] == job.get("_eid")
    if not job["company"]:
        return False
    t = e["text"].lower()
    c = job["company"].lower()
    return c.split()[0] in t or c in t


# ---------------- critic (reflection pass) ----------------

def critique(verdicts: list[dict], jobs: list, job_ev: dict, backend=None) -> list[dict]:
    """Reflection: list {job, problem} for verdicts that look wrong.

    Deterministic rules (fast, free). The LLM self-check now lives inside the
    synthesize prompt (one fewer round-trip); this pass enforces the outcome.
    Flagged verdicts are replaced by deterministic ones by the caller —
    problems surface in the trace, never silently.
    """
    issues = []
    for v in verdicts:
        i = v.get("job")
        if not isinstance(i, int) or not (0 <= i < len(jobs)):
            issues.append({"job": -1, "problem": "verdict points at no known job"})
            continue
        rs = v.get("reasons") or []
        if not (0 <= int(v.get("score", -1)) <= 100):
            issues.append({"job": i, "problem": "score outside 0-100"})
        if len(rs) < 1:
            issues.append({"job": i, "problem": "verdict has no reasons"})
    return issues


NEXT_STEPS = [
    {"text": "Never pay for a job or internship — no fee is ever refundable in these scripts.", "link": ""},
    {"text": "Verify on the official company site + AICTE National Internship Portal (free; stay inside it).", "link": "https://www.internship.aicte-india.org/"},
    {"text": "Money already sent or threats received? Call cybercrime helpline 1930 and file at the National Cyber Crime portal.", "link": "https://cybercrime.gov.in/"},
    {"text": "Asked to sign a bond? Get proper legal advice before signing — penalties must match real training investment.", "link": ""},
]


def _verify_paste_legacy(text: str, backend=None, emit=None) -> dict:
    """Paste-and-verify: judge any opportunity message. Budget: ≤3 SerpApi credits."""
    from . import claims as claimlib

    backend = backend or (GeminiBackend() if config.GEMINI_API_KEY else DeterministicBackend())
    trace, errors, evidence, spent = [], [], [], 0
    budget = 3
    mode = "LIVE" if config.SERPAPI_API_KEY else "FIXTURE (recorded, labeled)"
    text = (text or "").strip()[:4000]
    if not text:
        return {"error": "empty message", "trace": trace}
    _rec(trace, emit, {"kind": "extract", "note": "claim extraction from pasted text"})
    # Merged input: URLs hidden in the text are fetched and judged together.
    urls = re.findall(r"https?://[^\s)>\]]+", text)[:2]
    fetched_from = []
    for u in urls:
        got = fetch_url_text(u.rstrip(".,"))
        if got["ok"]:
            text = (text + "\n\n[Fetched page content]\n" + got["text"])[:8000]
            fetched_from.append(got["final_url"])
            _rec(trace, emit, {"kind": "tool", "tool": "fetch_url", "args": {"url": u[:60]}, "ok": True, "credits": 0})
        else:
            _rec(trace, emit, {"kind": "tool", "tool": "fetch_url", "args": {"url": u[:60]}, "ok": False, "note": got["error"]})
            errors.append(f"Could not read {u[:60]}: {got['error']}")
    cl = claimlib.extract(text)
    if not cl["companies"] and not cl["brand_hit"] and config.GEMINI_API_KEY and isinstance(backend, GeminiBackend):
        # LLM cross-check only when deterministic extraction found nobody —
        # otherwise it's a wasted round-trip on every paste.
        try:
            parsed = GeminiBackend._json(backend._call(
                "Extract from this opportunity message as JSON: " + text[:1500], CLAIM_SCHEMA))
            if parsed and parsed.get("company"):
                cl["companies"] = [parsed["company"]]
        except Exception as e:
            _rec(trace, emit, {"kind": "extract", "note": f"LLM cross-check failed ({type(e).__name__}) — deterministic claims kept"})
    company = (cl["companies"] + [cl["brand_hit"]] if cl["brand_hit"] else cl["companies"])
    company = company[0] if company else ""
    news_n = forum_n = 0
    presence: list = []
    news_items: list = []
    forum_items: list = []
    if company:
        _rec(trace, emit, {"kind": "plan", "note": f"fanout verify: {company}"})
        try:
            res = run_fanout(company, {"eid": 0})
            evidence = res["evidence"]
            spent = res["spent"]
            bad = [t for t, r in res["results"].items() if "error" in r]
            _rec(trace, emit, {"kind": "fanout", "tool": "news+presence+forums",
                          "args": {"company": company}, "ok": not bad, "credits": spent})
            news_items = res["results"].get("company_news", {}).get("news", [])
            presence = res["results"].get("company_presence", {}).get("presence", [])
            forum_items = res["results"].get("forums_search", {}).get("forums", [])
            news_n, forum_n = len(news_items), len(forum_items)
        except Exception as e:
            errors.append(f"Verify failed ({type(e).__name__}) — judging on message cues alone.")
            _rec(trace, emit, {"kind": "fanout", "tool": "news+presence+forums", "ok": False,
                          "note": f"{type(e).__name__}"})
    else:
        _rec(trace, emit, {"kind": "plan", "note": "no company named — judging on message cues alone"})

    job = {"title": "Pasted opportunity", "company": company, "location": "—", "via": "pasted message",
           "posted_at": None, "salary": " ".join(cl["money"][:2]), "schedule": "",
           "description": text, "apply": [], "share_link": "", "job_id": "", "_dupes": 1, "_eid": "E0"}
    for i, e in enumerate(evidence):
        e["id"] = f"E{i + 1}"
    job_ev = {0: {"news": news_n, "forums": forum_n, "presence": bool(presence),
                  "ids": [e["id"] for e in evidence],
                  "nums": set(range(1, len(evidence) + 1)),
                  "by_kind": {"posting": [],
                              "news": [e["id"] for e in evidence if e["kind"] == "news"],
                              "presence": [e["id"] for e in evidence if e["kind"] == "presence"],
                              "forums": [e["id"] for e in evidence if e["kind"] == "forums"]}}}
    s = scoring.score_paste(job, cl["cues"], news_hits=news_n,
                            has_presence=bool(presence), forum_hits=forum_n)
    category = claimlib.category_for(cl)
    label = claimlib.label_for(s["score"], category, proof=bool(presence))
    verdicts = [{"job": 0, "score": s["score"],
                 "reasons": [f"{r} [{job_ev[0]['ids'][0]}]" if job_ev[0]["ids"] else r for r in s["reasons"]]}]
    verdicts, corrections = validate_verdicts_paste(verdicts, job_ev)
    issues = critique(verdicts, [job], job_ev, backend)
    if issues:
        _rec(trace, emit, {"kind": "reflect",
                      "note": f"critic flagged {len(issues)} issue(s): " + "; ".join(i["problem"][:80] for i in issues[:3])})
    if corrections:
        _rec(trace, emit, {"kind": "validate", "note": f"{corrections} correction(s) applied"})
    _rec(trace, emit, {"kind": "synthesis",
                  "note": f"brain={backend.name}, category={category}, label={label}"})
    from urllib.parse import quote_plus

    from . import interview as iv

    role_key = iv.role_for(text)
    search_role = {"python": "python", "web": "web developer", "frontend": "frontend",
                   "data": "data analyst", "java": "java"}.get(role_key, "fresher")
    card = {**job, "score": s["score"],
            "band": "green" if s["score"] <= 30 else "amber" if s["score"] <= 60 else "red",
            "reasons": verdicts[0]["reasons"] if verdicts else s["reasons"],
            "label": label, "category": category, "claims": cl,
            "coach": {"opener": coach.opener_for(category),
                      "cons": coach.cons_for(cl["cues"]),
                      "closer": coach.closer_for(category)},
            "evidence": {
                "news": [{"title": (n.get("title") or "")[:100], "link": n.get("link", ""),
                          "source": {"name": ((n.get("source") or {}) if isinstance(n.get("source"), dict) else {"name": n.get("source", "?")}).get("name", "?")}}
                         for n in news_items] +
                        [{"title": (o.get("title") or "")[:100], "link": o.get("link", ""),
                          "source": {"name": o.get("source", "forum") if isinstance(o.get("source"), str) else "forum"}}
                         for o in forum_items],
                "presence": [{"title": (o.get("title") or "")[:100], "link": o.get("link", "")} for o in presence]},
            "summary": llm.grounded_bullets(verdicts[0]["reasons"] if verdicts else s["reasons"]),
            "next_steps": NEXT_STEPS,
            "source_url": fetched_from[0] if fetched_from else "",
            "search_role": search_role,
            "search_link": f"/search?role={quote_plus(search_role)}&location=India"}
    return {"mode": mode, "card": card, "errors": errors, "trace": trace,
            "spent": spent, "brain": backend.name, "budget": budget}


def validate_verdicts_paste(verdicts: list[dict], job_ev: dict) -> tuple[list[dict], int]:
    """Paste-mode validator: reasons must cite retrieved evidence, or say message-cue explicitly."""
    fixed, corrections = [], 0
    for v in verdicts:
        ok = [r for r in (v.get("reasons") or [])
              if any(f"E{e}" in r for e in job_ev[0]["nums"]) or "Message cue" in r]
        if not ok:
            corrections += 1
            continue
        v["reasons"] = ok
        try:
            v["score"] = max(0, min(100, int(v.get("score", 50))))
        except Exception:
            v["score"] = 50
            corrections += 1
        fixed.append(v)
    return fixed, corrections


# ---------------- follow-up chat (safe space) ----------------
# Stateless-safe: the caller passes the card; threads live in memory for the
# demo (a restart clears them — documented, not hidden).

THREADS: dict[str, list] = {}
MAX_THREADS = 100


def chat_answer(thread_id: str, card: dict, question: str, backend=None) -> dict:
    """Answer a follow-up about a verdict. Grounded in the card or honestly unsure."""
    backend = backend or (GeminiBackend() if config.GEMINI_API_KEY else DeterministicBackend())
    while len(THREADS) > MAX_THREADS:
        THREADS.pop(next(iter(THREADS)))
    thread = THREADS.setdefault(thread_id, [])
    question = (question or "").strip()[:1000]
    reply, via = "", "rules"
    if isinstance(backend, GeminiBackend) and config.GEMINI_API_KEY and question:
        try:
            reply = backend._call(coach.chat_prompt(question, card, thread)).strip()
            via = "gemini:" + backend.model
        except Exception:
            reply = ""
    if not reply and question:
        reply = coach.deterministic_reply(question, card, thread)
    if not reply:
        reply = "Ask me anything about this verdict — why I scored it so, what to do next, or what if it looks real to you."
    if question:
        thread.append({"q": question, "a": reply, "via": via})
    return {"reply": reply, "via": via, "thread": thread}


# ---------------- URL verdicts (fetch the JD, judge it) ----------------

def fetch_url_text(url: str) -> dict:
    """Fetch a posting URL and return visible text. Failures are explicit —
    JS-heavy/blocked pages tell the student to paste the text instead."""
    import httpx
    from html.parser import HTMLParser

    u = (url or "").strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return {"ok": False, "error": "URL must start with http:// or https://"}

    class Strip(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: list = []
            self.skip = False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "nav", "header", "footer"):
                self.skip = True

        def handle_endtag(self, tag):
            if tag in ("script", "style", "nav", "header", "footer"):
                self.skip = False

        def handle_data(self, data):
            if not self.skip and data.strip():
                self.parts.append(data.strip())

    try:
        r = httpx.get(u, timeout=10, follow_redirects=True,
                      headers={"User-Agent": "FirstJobVerifier/1.0 (student-safety demo)"})
        if r.status_code != 200:
            return {"ok": False, "error": f"page returned HTTP {r.status_code} — paste the text instead"}
        if len(r.content) > 500_000:
            return {"ok": False, "error": "page too large to judge — paste the text instead"}
        p = Strip()
        p.feed(r.text[:200_000])
        text = re.sub(r"\s+", " ", " ".join(p.parts))[:4000]
        if len(text) < 200:
            return {"ok": False,
                    "error": "page gave almost no readable text (JS-heavy or login-blocked) — paste the text instead"}
        return {"ok": True, "text": text, "final_url": str(r.url)}
    except Exception as e:
        return {"ok": False, "error": f"fetch failed ({type(e).__name__}) — paste the text instead"}


# ---------------- public drivers (stateless-first) ----------------
# Default brains run the resumable step() path (serverless-proof, and what
# /api/advance drives over HTTP). Custom planner brains (tests, experiments)
# keep the classic next_action loop via the legacy path.

_DEFAULT_BRAINS = None  # resolved lazily to avoid import-order issues


def _is_default_brain(backend) -> bool:
    return backend is None or type(backend) in (DeterministicBackend, GeminiBackend)


def run_agent(role: str, location: str, backend=None, emit=None) -> dict:
    if not _is_default_brain(backend):
        return _run_agent_legacy(role, location, backend, emit)
    st = new_search_state(role, location)
    backend = _backend(backend)
    for _ in range(12):
        for ev in step(st, backend):
            if emit:
                try:
                    emit(ev.get("kind", "step"), ev.get("tool") or ev.get("note", ""))
                except Exception:
                    pass
        if st.get("done"):
            break
    r = st["result"] or {"cards": [], "errors": st["errors"], "trace": st["trace"],
                         "spent": st["spent"], "brain": backend.name, "budget": st["budget"]}
    return {"mode": st["mode"], "role": role, "location": location, **r}


def verify_paste(text: str, backend=None, emit=None) -> dict:
    if not _is_default_brain(backend):
        return _verify_paste_legacy(text, backend, emit)
    st = new_verify_state(text)
    if not (st.get("text") or "").strip():
        return {"error": "empty message", "trace": []}
    backend = _backend(backend)
    for _ in range(8):
        for ev in step(st, backend):
            if emit:
                try:
                    emit(ev.get("kind", "step"), ev.get("tool") or ev.get("note", ""))
                except Exception:
                    pass
        if st.get("done"):
            break
    r = st.get("result")
    if not r:
        return {"error": "could not judge that message", "trace": st["trace"]}
    return {"mode": st["mode"], **r}
