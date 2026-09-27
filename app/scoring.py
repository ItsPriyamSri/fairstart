"""Deterministic normalization, dedup, and explainable risk scoring.

No ML, no LLM here. Every point has a visible reason so a student (and a judge)
can audit the score. Language is "risk signals", never a binary fraud verdict.
"""
import re

FEE_PAT = re.compile(
    r"(registration\s*fee|refundable|processing\s*fee|bond\s*security|document\s*"
    r"verification\s*(fee|charge)|pay\s*(rs|inr|₹)?\s*\d|deposit.{0,20}(rs|inr|₹)?\s*\d|fee.{0,20}(rs|inr|₹)\s*\d|challan|legal\s*dept)",
    re.I,
)
WHATSAPP_PAT = re.compile(r"(whatsapp|telegram)\s*(apply|number|only| sahibi)?", re.I)
GMAIL_PAT = re.compile(r"[a-z0-9._%+-]+@g?mail\.com", re.I)
POSTED_DAYS_PAT = re.compile(r"(\d+)\s*\+?\s*(day|week|month)", re.I)
SALARY_NUM_PAT = re.compile(r"(\d+(?:\.\d+)?)\s*(lpa|lakh)", re.I)


def normalize_job(j: dict) -> dict:
    det = j.get("detected_extensions") or {}
    return {
        "title": j.get("title", ""),
        "company": (j.get("company_name") or "").strip(),
        "location": j.get("location", ""),
        "via": j.get("via", ""),
        "posted_at": det.get("posted_at")
        or ((j.get("extensions") or [None])[0]),
        "salary": det.get("salary", ""),
        "schedule": det.get("schedule_type", ""),
        "description": j.get("description", "") or "",
        "apply": [
            {"title": a.get("title", ""), "link": a.get("link", "")}
            for a in (j.get("apply_options") or [])
            if a.get("link")
        ],
        "share_link": j.get("share_link", ""),
        "job_id": j.get("job_id", ""),
    }


def dedupe(jobs: list[dict]) -> list[dict]:
    """Fuzzy key: company + first 4 title tokens + city. Keeps first, counts dups."""
    seen: dict[str, dict] = {}
    for j in jobs:
        title_toks = re.findall(r"[a-z0-9+.#]+", j["title"].lower())[:4]
        city = (j["location"] or "").split(",")[0].strip().lower()
        key = f"{j['company'].lower()}|{' '.join(title_toks)}|{city}"
        if key in seen:
            seen[key]["_dupes"] = seen[key].get("_dupes", 1) + 1
            # merge apply links
            links = {a["link"] for a in seen[key]["apply"]}
            for a in j["apply"]:
                if a["link"] not in links:
                    seen[key]["apply"].append(a)
        else:
            j["_dupes"] = 1
            seen[key] = j
    return list(seen.values())


def posted_days_ago(posted_at: str | None) -> int | None:
    if not posted_at:
        return None
    m = POSTED_DAYS_PAT.search(posted_at.lower())
    if not m:
        if "hour" in posted_at.lower() or "today" in posted_at.lower() or "yesterday" in posted_at.lower():
            return 1 if "yesterday" in posted_at.lower() else 0
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n * (1 if unit.startswith("day") else 7 if unit.startswith("week") else 30)


def lpa_figures(text: str) -> list[float]:
    """All LPA/lakh figures in a blob of text (ranges yield both ends)."""
    return [float(m.group(1)) for m in SALARY_NUM_PAT.finditer(text or "")]


def median_lpa(jobs: list[dict]) -> float | None:
    """Median of per-job max LPA figure; None when no salary data present."""
    vals = []
    for j in jobs:
        figs = lpa_figures((j.get("salary") or "") + " " + j.get("description", ""))
        if figs:
            vals.append(max(figs))
    if not vals:
        return None
    vals.sort()
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def score_job(j: dict, news_hits: int = 0, has_presence: bool = False,
              set_median: float | None = None) -> dict:
    reasons: list[str] = []
    score = 0
    text = f"{j['title']}\n{j['description']}"

    if FEE_PAT.search(text):
        score += 35
        reasons.append("Fee language detected (registration/refundable/bond/challan) — genuine employers don't charge applicants (Naukri red flag).")
    if WHATSAPP_PAT.search(text):
        score += 15
        reasons.append("WhatsApp/Telegram-only application pattern — matches reported fresher-scam scripts.")
    if GMAIL_PAT.search(text):
        score += 10
        reasons.append("Gmail address in posting text — reputed firms use official domains.")
    if not j["company"]:
        score += 20
        reasons.append("No company name listed.")
    if not j["apply"]:
        score += 15
        reasons.append("No apply link captured — can't verify destination.")
    days = posted_days_ago(j.get("posted_at"))
    if days is None and not j.get("posted_at"):
        score += 5
        reasons.append("Posting date missing — freshness unverifiable.")
    elif days is not None and days > 30:
        score += 10
        reasons.append(f"Posted ~{days}d ago — likely stale repost.")
    m = SALARY_NUM_PAT.search((j.get("salary") or "") + " " + text)
    threshold = 8.0
    if set_median:
        threshold = max(8.0, 2 * set_median)
    if m and float(m.group(1)) >= threshold and re.search(r"fresher|junior|0-?\d?\s*yr|entry", text, re.I):
        score += 10
        basis = f"≥{threshold:g} LPA vs set median {set_median:g} LPA" if set_median else "≥8 LPA"
        reasons.append(f"High salary ({basis}) pitched at freshers — classic lure pattern.")
    if j.get("_dupes", 1) > 2:
        score += 10
        reasons.append(f"Same role reposted {j['_dupes']}× across boards — repost-farm pattern.")
    if news_hits > 0:
        score += min(15, news_hits * 5)
        reasons.append(f"{news_hits} scam/fraud-related news hit(s) for this company name — open Evidence before applying.")
    if has_presence and score > 0:
        score = max(0, score - 10)
        reasons.append("Company has an official web presence (official site/careers found) — mild positive, not a clean chit.")
    if not reasons:
        reasons.append("No classic risk signals found in text, date, or apply path. Still verify the apply domain before sharing documents.")
    score = max(0, min(100, score))
    band = "green" if score <= 30 else "amber" if score <= 60 else "red"
    return {"score": score, "band": band, "reasons": reasons}


PASTE_BUMPS = {  # extra points per cue family for pasted messages (no board metadata)
    "task_lure": 25, "guarantee": 15, "upi": 10, "threat": 10, "chat_only": 10,
    "gmail_hr": 10, "pay_cert": 45, "commission_only": 30, "unpaid_labor": 15,
    "bond": 10, "sells_fakery": 30, "fee": 0,  # fee already counted by score_job
}

# Hard floors: certain cue families can never score below these — contradiction
# rule (scam evidence overrides any positive signal like web presence).
SCORE_FLOORS = {"fee": 61, "threat": 61, "sells_fakery": 61, "upi": 61,
                "task_lure": 61, "pay_cert": 55, "commission_only": 55}

# Static benchmark (labeled guidance, Internshala/Careers360 via research):
# real avg intern stipend ≈ ₹8,000/mo. Monthly-equivalent far above = lure.
AVG_STIPEND_MONTHLY = 8000
MONTHLY_PAT = re.compile(
    r"(?:₹|rs\.?|inr)\s*([\d,]+)(?:\s*(?:/|per)\s*(month|day))?|\b([\d,]+)\s*(?:/|per)\s*(month|day)\b", re.I)


def monthly_inr(text: str) -> list[float]:
    """Rupee figures normalized to monthly equivalents (×30 for per-day)."""
    vals = []
    for m in MONTHLY_PAT.finditer(text or ""):
        raw = (m.group(1) or m.group(3) or "").replace(",", "")
        try:
            amt = float(raw)
        except ValueError:
            continue
        unit = (m.group(2) or m.group(4) or "").lower()
        vals.append(amt * 30 if unit == "day" else amt)
    return vals


def score_paste(job: dict, cues: list[dict], news_hits: int = 0,
                has_presence: bool = False, forum_hits: int = 0) -> dict:
    """Score a pasted opportunity: base text signals + cue bumps + evidence."""
    s = score_job(job, news_hits=news_hits, has_presence=has_presence)
    seen = set()
    for c in cues:
        name = c["cue"]
        if name in seen:
            continue
        seen.add(name)
        bump = PASTE_BUMPS.get(name, 0)
        if bump:
            s["score"] += bump
            s["reasons"].append(f"They're {c.get('label', c['cue'])}: “{c['quote']}”")
    if forum_hits > 0:
        s["score"] += min(15, forum_hits * 5)
        s["reasons"].append(f"{forum_hits} forum thread(s) discussing scams under this company name — open Evidence.")
    cue_names = {c["cue"] for c in cues}
    floors = [SCORE_FLOORS[c] for c in cue_names if c in SCORE_FLOORS]
    if floors:
        s["score"] = max(s["score"], max(floors))
        s["reasons"].append("Hard floor applied: these cue types override any positive signal — scam evidence beats a shiny website.")
    for fig in monthly_inr(job.get("description", "") + " " + job.get("salary", "")):
        if fig >= 4 * AVG_STIPEND_MONTHLY:
            s["score"] = min(100, s["score"] + 10)
            s["reasons"].append(f"Pay figure ≈₹{fig:,.0f}/mo vs ~₹{AVG_STIPEND_MONTHLY:,}/mo average intern stipend (Internshala/Careers360 benchmarks) — classic lure sizing.")
            break
    s["score"] = max(0, min(100, s["score"]))
    s["band"] = "green" if s["score"] <= 30 else "amber" if s["score"] <= 60 else "red"
    return s
