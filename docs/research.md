# Research — SerpApi India Hackathon 2026

Retrieval date for all sources below: **2026-09-27 (UTC)**. Official rules take precedence over third-party summaries and over the prompt text.

## 1. Official hackathon facts (verified)

- Hackathon site: https://serpapi.github.io/serpapi-india-hackathon-2026/
- Rules: https://serpapi.github.io/serpapi-india-hackathon-2026/rules.html
- Terms: https://serpapi.github.io/serpapi-india-hackathon-2026/terms.html
- Announcement: https://serpapi.com/blog/introducing-the-serpapi-india-hackathon-2026/ (2026-09-22)

Verified details:

| Item | Evidence |
|---|---|
| Dates | Sep 1, 2026 00:00 IST – Oct 10, 2026 23:59 IST (`rules.html` §1, `terms.html` §2). Timezone IST (UTC+5:30). |
| Format | Fully online/async, free, any language (`index`, `rules.html` §3). |
| Eligibility | 18+, reside in India; solo or teams ≤5; SerpApi staff/contractors + family excluded from awards (`rules.html` §2). Prompt said "Indian residents 18+" — matches. |
| Deadline | **Oct 10, 2026 23:59 IST** (`index`, `rules.html` §4). Matches prompt's "extended" claim. Third-party aggregator allhackathons.com still shows Oct 5 — stale, do not rely on it. |
| Submission | GitHub sign-in on site; public GitHub repo + setup docs; demo video <3 min screen recording running locally, public/unlisted link opening in incognito; description + track; lead name/email/phone/occupation/experience + teammate names/emails; SerpApi usage explanation; pre-existing-project disclosure; AI-tool disclosure; accept Rules+Terms; max 3 active projects per account; "Submit project" required (draft ≠ entry) (`rules.html` §4, `terms.html` §4). |
| Demo | Narration optional, may speed up; quality doesn't affect judging (`rules.html` §4). |
| Judging | Unweighted: idea strength, originality, technical complexity, usefulness, meaningful SerpApi usage. Judges may review repo history/code/docs/demo; SerpApi final discretion (`rules.html` §6). No fixed weights — prompt's "core judging criterion" phrasing is consistent but weights don't exist. |
| Meaningful use | "Material contribution… isolated or cosmetic API call insufficient," SerpApi sole discretion (`rules.html` §3). |
| Tracks (6) | AI Agents, Open-Source Integrations, Travel & Local Discovery, Commerce & Market Intelligence, Knowledge & Public Interest, Open Innovation (`rules.html` §3, blog ideas list). SerpApi may re-track entries. |
| Prizes | 1st ₹1,00,000+15k credits, 2nd ₹40k+10k, 3rd ₹20k+10k; Best-in-Track 10k credits ×6; Best-from-Community ₹10k+5k ×4 partners (BangPypers, HydPy, TriPy, AI Geeks Chennai); every valid submission 1,000 credits. One competitive award per project; participation credits stack. 100 credits = $1 usage (`index` prizes, `rules.html` §7). Prompt's ₹1L/40k/20k figures match. |
| AI tools | Allowed, must name tools + contribution; no judging effect; user responsible for accuracy/security/licensing (`rules.html` §5). |
| Existing projects | Allowed if submitted version has meaningful SerpApi use + disclosure (`rules.html` §3). |
| Credits for building | Free SerpApi account: 250 searches/month (`index` step 1, blog). |
| Governing docs | Terms control over Rules on conflict; Texas governing law + binding individual arbitration (with small-claims carve-out, mandatory-law savings); publicity license to SerpApi; no confidentiality for public materials; do not put keys/PII in repo (`terms.html` §§1,4,8,10). |

Unresolved uncertainties: exact submission form fields beyond rules list (portal is JS-driven `submit.html`); judging/winner-announcement dates ("will be announced"); deployment not required (demo is local run — no hosted-deploy requirement found).

## 2. SerpApi API facts (verified 2026-09-27)

- Catalog: https://serpapi.com/search-engine-apis (100+ engines).
- Pricing: https://serpapi.com/pricing — Free $0: 250 searches/mo, 50/hr throughput. Starter $25/1k, Developer $75/5k, Production $150/15k, Big Data $275/30k; overage = early-renew (full re-buy), no pay-as-you-go; unused searches reset monthly (downgrade leftovers → Extra Credits). Only **successful** searches count; cached/errored/failed free; result depth doesn't change cost (100 results = 1 search = empty = 1 search). Cache TTL 1h on exact-param match; `no_cache=true` forces spend. Throughput = 20% of monthly/hr on self-serve tiers.
- Errors: https://serpapi.com/api-status-and-error-codes — HTTP 200/400/401/403/404/410/429/500/503; `search_metadata.status`: Processing→Success|Error; empty results still `Success` with `error` note; 429 = throughput cap OR out of searches.
- Google Jobs API: https://serpapi.com/google-jobs-api — `engine=google_jobs`, required `q`; optional `location` (city-level recommended), `gl`/`hl`/`google_domain`, `lrad`, `uds`, `next_page_token` (10 results/page). Response: `jobs_results[]` (title, company_name, location, via, share_link, extensions/detected_extensions posted_at/salary/schedule_type, description, job_highlights, apply_options[].title+link, job_id), `filters[]`, `serpapi_pagination.next_page_token`.
- Google News API: https://serpapi.com/google-news-api — `engine=google_news`, `q`, `gl`/`hl`, `so` (0 relevance/1 date), topic/publication/story/section tokens. Response `news_results[]` (title, source.name, link, date/iso_date, thumbnail). Used for company-legitimacy signals.
- Google Search API (`engine=google`, https://serpapi.com/search-api): organic results + answer boxes, knowledge graph, related questions; supports `q`, `location`, `gl/hl`, `num`, `start`. Used sparingly for company-presence check (official site, reviews).
- Latency/pricing implication: each engine call = 1 search. Budget design (agent-enforced): 1 Jobs + 3 per verified company (news+presence+forums fan-out), cap 2 = max 7/search; ~35 searches fit in free 250/mo. Cache hits free — local SQLite mirror keyed on exact params with 1h TTL matches upstream semantics.
- Attribution/terms: no special attribution string found in engine docs; SerpApi legal terms govern reuse (https://serpapi.com/legal). We link every fact to its original `share_link`/`apply_options.link`/news `link` in UI (provenance requirement from prompt, good practice regardless).
- Account/free-tier usability: not yet verified with a live key (no key provided). Integration is built against documented responses + recorded fixtures; live path is clearly labeled and untested until key added. No assumption of extra free allowance made.
- Agent brain (Gemini 3.5 Flash-Lite, `gemini-3.5-flash-lite`): stable model ID verified 2026-09-27 (https://ai.google.dev/gemini-api/docs/models, model page https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite — supports function calling + structured outputs, 1M-token input, "optimized for high-volume agentic workflows"; GA since 2026-07-21, retirement ≥2027-07-21). Free tier via AI Studio (commonly ~250 req/day on Flash-class keys; limits vary by project/region and Google cuts them without notice — usagebox/aifreeapi guides, retrieved 2026-09-27). Our use ≈ 2–4 LLM calls/search, far inside free quota. Structured outputs via REST `generationConfig.responseMimeType: application/json` + `responseSchema` (verified in Gemini docs + Firebase AI Logic guides, 2026-09-27) — planner/extractor/verdict/critic schemas implemented, text-JSON fallback retained. WARNING from community reports: enabling billing on a project kills its free tier — keep demo on a billing-free project. LLM is strictly optional: deterministic brain is default, every LLM citation is validator-checked, every failure falls back visibly.
- Forums engine (`engine=google_forums`, https://serpapi.com/google-forums-api, verified 2026-09-27): `q` required, `gl/hl` supported, response `organic_results[]` (title/link/snippet/source — Reddit threads). Query shape `"<company>" scam OR fraud OR fake internship`. Catches victim discussions boards/news miss; same 1-credit + 1h-cache economics.

## 3. Competitors (live product pages, 2026-09-27)

1. **Perplexity Deep Research / Computer** — https://www.perplexity.ai/, https://www.perplexity.ai/hub/products/deep-research — cited-answer engine + multi-step research reports across hundreds of sources; free core + Pro $20/mo. Solves: general cited Q&A. Gap: not a job-trust layer — no dedup of job boards, no scam-risk scoring, no freshness/posted-at normalization, no company-legitimacy fusion for fresher roles. Validates grounded-citation UX we copy (inline sources), but our wedge is narrower and action-oriented (apply / skip decision).
2. **Naukri.com (Security Centre + report-fake-job flow)** — https://company.naukri.com/landing-page/fakejobtrend/new/index.html, https://www.naukri.com/imposter/report-fake-job-recruiter, https://www.naukri.com/faq/job-seeker-security-advice — India's largest job board with post-hoc scam education and reporting. Solves: listing supply + after-the-fact advice. Gap: advice is generic ("don't pay"), not per-listing risk evidence at decision time; no cross-board dedup; no freshness/company-presence signals fused into each card. Our product puts those signals inline before apply.
3. **LinkedIn Jobs / generic boards + Dependabot-style automation** (representative: LinkedIn job search; Snyk/Dependabot for the rejected upgrade-advisor concept) — boards optimize for volume/applications, not verification; upgrade tools (Dependabot, Snyk) solve CVE/version bumps but don't fuse live community pain (StackOverflow/Reddit breakage reports, changelog semantics) into a migration-risk brief. Gap (for jobs): no per-posting scam model; gap (for upgrade concept): incumbents own the version-feed but not the live-breakage synthesis. Jobs gap is broader and more India-relevant, hence selection.

## 4. Real-user pain evidence (credible, firsthand)

- Naukri Security Centre lists red flags matching our heuristic set: lucrative salary + min experience, "best fit for all", multi-location, poorly written JD, instant offer without interview, reputed-company name + public email domain, little/no web presence; advises never pay, verify person, check reviews. (company.naukri.com fraud-alert page, retrieved 2026-09-27.)
- Decode/BOOM investigation "How Fake Recruiters Are Trying To Scam India's Job Seekers" (2023-06-20, updated 2025-10-06): documents penalty/challan threats (₹49k/₹10k), fake HCL/Tata interviews, "refundable" documentation fees (₹15k), data-entry task scams, impersonation of Naukri HR. https://www.decodeinternet.in/decode/impact/how-fake-recruiters-are-trying-to-scam-indias-job-seekers-22300
- Firsthand LinkedIn posts (2023–2025): Ajinkya Nishane Red-Hat-Pune refundable-fee + fake telephonic interview + legal-threat script; Aritra Chowdhury HCL ₹1000 interview-ID demand; Ayush Tathe Naukri-name premium-fee flow; ConsumerComplaintsCourt Aug-2026 HCL/Naukri-FastForward ₹500+₹2000+bond-security ₹6800 case. Pattern is stable over years, fresher-targeted, fee + Gmail-domain + WhatsApp/phone-only process. No interviews were manufactured by us; all links recorded in concept-decision appendix.
- Implication: a per-listing, evidence-linked risk score (fee language, contact-channel, domain, salary outlier, freshness, company presence) addresses exactly the cues victims report missing at decision time.
- Scale (2026): Monster survey — 95% of job seekers report suspicious offers, 53% targeted; Gen Z 2× more likely than boomers to encounter scams; ~23% of those who encounter one become victims; avg loss ~$8,900 (US; https://www.monster.com/career-advice/research/job-scam-statistics, https://us.norton.com/blog/research/job-scam-statistics, retrieved 2026-09-27). India: "nearly 1 in 3 postings on free portals fake or reposted," ~101% surge in employment scams 2024-25, ~40% YoY rise per Norton 2024 (LinkedIn post by Richik Sinha Roy citing these figures, retrieved 2026-09-27 — treat portal-share figure as claimant's, direction corroborated by Decode/BBB). Heidmalm study of 2,670 social posts: top tactics = suspicious contact info, unrealistic salary, misleading JD; WhatsApp/phone = ~22% of contact (https://heimdalsecurity.com/blog/job-scam-social-media-study). Internshala 2026 notes WFH-fake-opening wave in India (https://internshala.com/blog/job-scams).

## 5. What this means for build

- Track: **Knowledge & Public Interest** (official example: "Use Google Jobs results to help people find their first developer role"). Multi-engine but Jobs-led keeps SerpApi material, not decorative.
- Budget: ≤7 SerpApi calls (agent budget)/search, ≤3/paste, 15s timeout, 1 retry on 429/5xx only, SQLite 1h cache, fixture fallback labeled as such. Free-tier safe.
- LLM: optional Gemini adapter, grounded-only (cites only retrieved items, admits unknowns); deterministic heuristic path is default so product works with zero LLM key.
- No paid services, no public deploy, no publish without approval. Keys server-side only.
