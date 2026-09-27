# Architecture explained (study sheet)

## The agent loop (what makes it an agent, not a script)
Fixed scripts always run the same steps. Our agent (`app/agent.py`) **decides** each step:
`goal → planner picks a tool → tool runs (SerpApi, 1 credit) → evidence grows → planner picks next → budget hit or evidence sufficient → synthesize verdicts → citation validator → cards`.
- **Tools:** `jobs_search`, `company_news`, `company_presence`. Unknown tools are refused; over-budget calls are denied — both recorded in the trace.
- **Brains:** `DeterministicBackend` plans (verify each discovered company — the only sane policy; an LLM planner cost ~25s/run for zero better decisions, so it was cut) and `GeminiBackend` (`gemini-3.5-flash-lite`) judges evidence via structured-output synthesis with built-in self-check. Switching brains changes neither the tools nor the budget.
- **Guardrails:** finish with unverified companies + unspent budget is overridden to the next fan-out; unknown/over-budget calls denied. Every override shows in the trace.
- **Grounding lock:** every verdict reason must cite evidence IDs (`[E1]`) belonging to that job; the validator replaces failures with deterministic verdicts and says so in the trace. The LLM can never invent a source, and no failure is ever hidden (planner/synthesis errors fall back + log).
- **Inspectability:** each run renders its full trace (plan/tool/deny/validate/synthesis) plus `spent/budget` credits — the demo literally shows the agent thinking.

## Data flow
Search: `goal → planner → jobs (1 call) → dedupe → fan-out verify per company (news+presence+forums concurrently, 3 calls) → synthesize → validate → critic → cards → snapshot`.
Paste: `message → claim extractor (3 cue families) → fan-out verify company (≤3 calls) → category-aware verdict + next steps → snapshot`.
`/history` lists saved snapshots; `/history/{id}` shows score deltas vs previous same-query run; `/export.csv` downloads the snapshot.

## Why each piece exists
- **FastAPI+Jinja (no JS framework):** runs on i5/16GB, zero Node, demo-fast, interview-explainable.
- **serpapi_client.py:** single SerpApi boundary; timeout 15s; retry once on 429/5xx only (safe: searches are idempotent reads); exact-param SQLite cache (1h, mirrors upstream free-cache semantics).
- **scoring.py:** deterministic, ML-free heuristics drawn from Naukri red flags + reported scam scripts (fee/challan, WhatsApp-only, Gmail, salary lure, stale, missing apply, repost farm). Salary-lure threshold is set-relative (≥ max(8 LPA, 2× result-set median)), so it adapts per query. Conservative: middle "amber" band, reasons always shown, wording is "risk signals" not "fraud."
- **agent.py:** the agentic loop (brains, tools, budget, validator, critic) — see section above. Deterministic scorer (`scoring.py`) + cue packs (`claims.py`) survive as the signal library + fallback, so the agent degrades gracefully instead of dying.
- **Harness map (why it holds up):** tool registry (4 tools + deny rules) · explicit EXTRACT→VERIFY→REFLECT→VERDICT stages · structured-output schemas (planner/verdicts/critic/claims) with text fallback · parallel fan-out (ThreadPoolExecutor, renumbered citations) · validator + critic reflection · hard budgets (7 search / 3 paste) with stopping rules · full trace observability · SQLite memory across runs. Model = interchangeable CPU; harness does the reliability work.
- **Resume + prep (local, free):** `resume.py` parses PDFs with pypdf (honest errors for scans/oversize), extracts ~100-skill vocabulary + level; per-card Match% is skill-overlap, a separate axis from trust — fit and safety never conflated. `interview.py` maps role→topics, 7-day plans from gaps, tiny practice bank. Resume stays on-device (never sent to SerpApi); chat serves plans/quizzes from these structures.
- **Self-sustaining loop:** fake verdicts end in a prefilled real-search CTA + chat "find me real jobs" intent; genuine cards lead to prep; prep gaps lead back to real postings.
- **store.py + summary/filters:** every run persisted to SQLite (free — no SerpApi cost) for snapshot history, cross-run score deltas, and CSV export; header stats (risk distribution, median LPA, freshness) and hide-risky/hide-senior filters are pure local compute.
- **llm.py:** isolated adapter; default extractive pass, no new facts. If GEMINI key set it may only rephrase given reasons. UI labels output "generated rephrasing" vs "retrieved evidence."
- **fixtures/:** recorded responses shaped like documented schemas; used for tests + labeled demo fallback. Never presented as live.

## SerpApi choices
- `google_jobs`: only source with structured fresher postings (posted_at, salary, apply_options, share_link). Indispensable.
- `google_news`: company-legitimacy signal (scam/fraud hits). Changes scores.
- `google` organic: official-presence check (careers/site). Mild positive only.
- Budget: 1 + ≤3×companies(≤2) = ≤7 credits/search → ~35 searches in free 250/mo. Cache hits free.

## Grounding & errors
- Every card links originals (share_link, apply links, news/presence links). Empty results → "no results, broaden query." Upstream Error status / HTTP fail → error banner + labeled fixture, never silent. Missing company/date/apply → explicit penalty + "unverifiable" text.

## Tradeoffs
- Heuristics over model: explainable, zero-cost, but can false-positive on genuine consultancies → mitigated with amber band + reasons + "verify domain" copy.
- Top-3 verify cap: saves credits, may miss tail companies → tail still scored on text/date/apply signals.
- No JS: less flashy, but reliable local demo.

## Tests
`test_scoring` (red/green/dedupe/malformed/paste-bumps), `test_serpapi_adapter` (cache-key, fixtures, key-guard), `test_e2e_smoke` (pipeline ordering + HTTP pages), `test_snapshots` (median/outlier, summary, filters, snapshot history + deltas + CSV export), `test_agent` (deterministic run, budget cap, unknown-tool deny, citation-validator correction, broken-brain fallback), `test_claims_paste` (4-input extractor categories, 4 paste verdicts, fan-out uniqueness, critic rules, structured-output schema wire, /verify pages), `test_calibration` (floors, benchmark lure, thin-evidence honesty, merged URL+text), `test_url_verdict` (fetch/strip, bad-scheme + short-page + error honesty, route verdicts), `test_coach_chat` (voice, 5 intents, threads, mocked Gemini, route flow), `test_resume_prep` (skills/level, match/gaps, PDF paths, interview maps, upload→match flow, fake→real loop, chat jobs/prep/quiz). 62 passed 2026-09-27.

## Likely judge questions
- "Works without SerpApi?" No — remove Jobs data and there are no cards; remove News/Search and trust scores lose their discriminating signals. (Passes test a.)
- "Why not Perplexity?" It answers questions; this decides apply/skip per listing with board-level dedup + risk evidence.
- "False accusations?" We never label "fraud" — scores + quoted patterns + links; user decides.
- "Why an agent, not a fixed script?" The planner adapts verification to what it finds (new company → verify it; budget low → finish early) and the trace proves it; the citation validator keeps the LLM honest.
- "Cost?" $0 demo; ~7 credits max/live search, ~3/paste on free tier; LLM ≈ 2–4 free-tier Gemini calls, optional.
