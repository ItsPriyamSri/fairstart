# FairStart

Fresher opportunity-verdict agent for Indian students (SerpApi India Hackathon 2026, Knowledge & Public Interest track): search role+city **or paste any WhatsApp/Telegram/email/poster text**; the agent extracts checkable claims, verifies each against live SerpApi evidence (Jobs + News + Search + Forums), and returns category-aware verdicts (LIKELY SCAM / EXPLOITATIVE / LEGAL-GRAY / UNVERIFIABLE / LIKELY GENUINE) with quoted cues and safe next steps. Track: **Knowledge & Public Interest**.

## Why SerpApi is essential
No Jobs data → no search product; no News/Forums/Search → no verdict. `google_jobs` supplies postings; `google_news` + `google_forums` (victim threads) supply legitimacy signals; `google` organic checks official presence. Each changes the outcome — remove SerpApi and the agent has nothing to reason over (not a decorative call). Pasted-message mode costs ≤3 credits (one news+presence+forums fan-out).

## Run locally
```bash
cp .env.example .env   # add SERPAPI_API_KEY for live; without it you get labeled fixture demo
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8123
# open http://127.0.0.1:8123/ → search role+city, or paste a suspicious message
```

## Test
```bash
python -m pytest -q   # 62 passed 2026-09-27 (scoring, adapter, e2e, snapshots, agent, claims/paste, calibration, url, resume/prep/chat, guards)
```

## Env vars
`SERPAPI_API_KEY` (live path; optional), `GEMINI_API_KEY` (agent brain upgrade; optional — deterministic brain is default), `GEMINI_MODEL` (default `gemini-3.5-flash-lite`), `MAX_VERIFY_COMPANIES=2`, `SERPAPI_TIMEOUT_S=15`, `CACHE_TTL_S=3600`. Keys stay server-side, never in Git/logs. Resume PDFs stay in local SQLite, never sent to SerpApi.

## Agent
Planner → SerpApi tools (`jobs_search`, `company_news`, `company_presence`, `forums_search`) → verdicts with `[E#]` citations → validator → critic → cards. Hard budget: max 7 SerpApi credits/search run, 3/paste run; unknown/over-budget calls denied and shown. Full trace + spend badge render on every results page. Gemini brain reasons over the same evidence; citation failures fall back visibly — the app never needs the LLM.

## Safe-space voice + chat
Verdicts speak like a protective senior (`app/coach.py`): warm opener, concrete cons with the student's own quoted words ("what this could cost you"), closer — blame the scammer, never the student. Every verdict page has follow-up chat (`/chat`, threads in server memory for the demo): push back, ask why, dig deeper. Deterministic intent router (why/next/pushback/safe/fallback) answers from card evidence only; Gemini path uses the same facts with an evidence-only prompt and "I don't know" honesty.

## Three ways in
Search role+city (live Jobs verdicts with proof-gated labels), or one merged box: paste message text, posting URLs, or both — links auto-fetched, everything judged together. (The old separate URL form still works at `/verify-url`.)

## Resume, gaps, prep, loop
Upload your PDF at `/profile` (stored only on this machine, never sent to SerpApi): every job shows **Match%** (skill overlap — a separate axis from trust) + missing-skill gaps + role interview topics. Genuine verdicts include an interview-prep section; chat serves 7-day plans and practice questions. Fake verdicts end with a **real-jobs redirect** (`/search` prefilled at your level) — scam → real search → prep: a self-sustaining loop.

## One history, same pages, session chat cache
`/history` lists every past check (searches + verdicts); opening one re-renders the **same full UI** — results cards or verdict + chat — not a separate mini page. Runs also carry their trace/brain/spend metadata (old DBs migrate silently). Chat threads additionally persist in the browser tab session (`sessionStorage`, server thread wins on conflict), so back-navigation and reloads keep the conversation.

## Architecture
Agent loop (plan → act → synthesize) → Jobs (1 call) → dedupe → top companies × News+Search+Forums fan-out → grounded verdicts with [E#] citations → summary header + snapshot saved → cards with Retrieved-vs-Generated sections. Snapshots page shows score changes over time; CSV export for placement cells. Every run shows its agent trace. See `docs/architecture-explained.md`.

## Cost
$0 demo. Live search ≈ 7 credits max (~35 queries fit); paste-verify ≈ 3 max free 250/mo. Cache hits free (1h TTL). No paid services, no deploy.

## Limits (honest)
- Live path untested (no key provided) — built against documented schemas + recorded fixtures; banner labels mode.
- Heuristics can false-positive on genuine consultancies → amber band + reasons shown, "risk signals" wording.
- Fixture cities/roles limited; tail companies beyond top-2 get text-only scoring.
- URL fetcher: no JS rendering, no login walls, no private-network guard — local-demo scope; failures say "paste the text instead."
- Chat threads live in server memory (restart clears them); resume stays in local SQLite only.
- Screenshots: none (UI verified via TestClient + curl 2026-09-27).

## AI disclosure
Muse Spark (OpenCode agent) for research/code/docs/tests; web search for source verification. Runtime agent: deterministic planner by default, optional Gemini 3.5 Flash-Lite brain. All code executed and tested locally (62 tests). No auto-publish/submit.
