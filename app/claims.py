"""Claim + cue extraction from pasted opportunity text (WhatsApp/Telegram/email/poster).

Deterministic first: regex cue packs with quote spans for three families —
outright fraud, gray-zone exploitation, self-harm traps. An LLM may
cross-check when keyed, but every cue shown to the user is a verbatim quote.
"""
import re

CUE_PACKS = {
    # family A: outright fraud
    "fee": (re.compile(r"(registration\s*fee|refundable|processing\s*fee|bond\s*security|verification\s*(fee|charge)|deposit|unlock\s*(fee|charge)|pay\s*(rs|inr|₹)?\s*\d|₹\s*\d|challan|penalt)", re.I), "fraud"),
    "upi": (re.compile(r"(upi(\s*(id|handle|pin))?|qr\s*code|gpay|phonepe|paytm|wallet|personal\s*(account|number)|bank\s*(transfer|details))", re.I), "fraud"),
    "guarantee": (re.compile(r"(guaranteed?\s*(stipend|ppo|placement|job|offer)|100%\s*(placement|job|guarantee)|no\s*interview|instant\s*(selection|offer|joining)|direct\s*(selection|joining))", re.I), "fraud"),
    "chat_only": (re.compile(r"(whatsapp|telegram)\s*(only|interview|apply)|(send|share).{0,30}(documents|aadhaar|pan|photo|resume).{0,20}(whatsapp|telegram)", re.I), "fraud"),
    "gmail_hr": (re.compile(r"[a-z0-9._%+-]+@(gmail|yahoo|hotmail|outlook|rediffmail)\.com", re.I), "fraud"),
    "task_lure": (re.compile(r"(like\s*(videos?|posts?|reels?)|subscribe|rate\s*(products?|hotels?)|daily\s*tasks?|earn.{0,12}\d[\d,]*.{0,12}(per\s*(day|month)|/day|/month|lpa)|work\s*from\s*home.{0,20}\d)", re.I), "fraud"),
    "threat": (re.compile(r"(legal\s*(dept|action|notice)|court|challan|blacklist|police|fir\b|lawsuit|penalty.{0,20}(pay|rs))", re.I), "fraud"),
    # family B: gray-zone exploitation
    "pay_cert": (re.compile(r"(certificate\s*(fee|charge|price)|pay.{0,30}(certificate|enroll|training|masterclass)|(basic|premium|advanced)\s*plan|recorded\s*sessions?)", re.I), "exploit"),
    "commission_only": (re.compile(r"(campus\s*ambassador|\d+%\s*commission|commission(\s*only|\s*\d+%)?|performance-based\s*(stipend|pay)|per\s*enrollment|referral\s*(bonus|income))", re.I), "exploit"),
    "unpaid_labor": (re.compile(r"(unpaid|no\s*stipend|stipend\s*(after|on\s*completion)|extend.{0,20}(internship|probation)|client\s*projects?.{0,20}(unpaid|no\s*pay))", re.I), "exploit"),
    "bond": (re.compile(r"((employment|service|training)\s*bond|sign.{0,20}bond|leave.{0,30}(pay|penalty|₹|rs)|notice.{0,20}(buyout|pay))", re.I), "bond"),
    # family C: self-harm (message SELLING fakery to the student)
    "sells_fakery": (re.compile(r"(buy|get|provide).{0,40}(experience\s*(letter|certificate)|fake\s*(experience|certificate|degree|offer))", re.I), "selfharm"),
}

COMPANY_PAT = re.compile(
    r"\b([A-Z][A-Za-z&.,'’\- ]{2,60}?(?:Technologies|Labs|Solutions|Systems|Services|Enterprises|Pvt\.?(?:\s*Ltd\.?)?|Ltd\.?|Inc\.?|LLP|Private\s*Limited))\b")
FROM_PAT = re.compile(r"(?:from|at|with|@)\s+([A-Z][A-Za-z&.\- ]{2,40}?)(?:\s+(?:HR|team|hiring|recruit|is|has|for|,)|\s*$)", re.M)
MONEY_PAT = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(lpa|lakh|k|/month|per\s*month|/day)?", re.I)
BIG_BRANDS = ["tcs", "infosys", "wipro", "hcl", "accenture", "cognizant", "tech mahindra", "capgemini", "amazon", "flipkart", "google", "microsoft"]


def _quote(text: str, start: int, end: int, limit: int = 220) -> str:
    """Expand a match to full-sentence context so quotes never cut mid-word."""
    past = [text.rfind(".", 0, start), text.rfind("!", 0, start),
            text.rfind("?", 0, start), text.rfind("\n", 0, start)]
    s = max([p + 1 for p in past] + [0])
    future = [p for p in (text.find(".", end), text.find("!", end),
                          text.find("?", end), text.find("\n", end)) if p != -1]
    e = min(future + [len(text)])
    q = text[s:e].strip()
    return q if len(q) <= limit else q[:limit].rstrip() + "…"


CUE_LABELS = {
    "fee": "asking for money", "upi": "UPI/bank payment", "guarantee": "guaranteed job",
    "chat_only": "chat-only process", "gmail_hr": "free-email HR", "task_lure": "too-good task pay",
    "threat": "threats", "pay_cert": "paid certificate", "commission_only": "commission-only work",
    "unpaid_labor": "unpaid work", "bond": "job bond", "sells_fakery": "selling fake letters",
}


def extract(text: str) -> dict:
    """Returns claims: cues with quotes, company guess, money figures, contact channels."""
    cues = []
    for name, (pat, family) in CUE_PACKS.items():
        m = pat.search(text or "")
        if m:
            cues.append({"cue": name, "family": family,
                         "label": CUE_LABELS.get(name, name),
                         "quote": _quote(text, m.start(), m.end())})
    companies = COMPANY_PAT.findall(text or "") + [m.group(1).strip() for m in FROM_PAT.finditer(text or "")]
    companies = list(dict.fromkeys(c.strip(" .,") for c in companies if len(c.strip()) > 2))[:3]
    money = [f"{m.group(0).strip()}" for m in MONEY_PAT.finditer(text or "")][:5]
    low = (text or "").lower()
    brand_hit = next((b for b in BIG_BRANDS if b in low), None)
    return {"cues": cues, "companies": companies, "money": money, "brand_hit": brand_hit,
            "has_company": bool(companies or brand_hit)}


def category_for(claims: dict) -> str:
    """Deterministic first-pass category; the agent's critic may adjust, never silently."""
    fams = {c["family"] for c in claims["cues"]}
    if "fraud" in fams:
        return "scam"
    if "selfharm" in fams:
        return "selfharm"
    if "bond" in fams:
        return "bond"
    if "exploit" in fams:
        return "exploit"
    if not claims["has_company"]:
        return "unverifiable"
    return "clean"


def label_for(score: int, category: str, proof: bool = False) -> str:
    """Category-aware labels. Thin evidence can NEVER read as genuine:
    LIKELY GENUINE requires proof (official presence found)."""
    if category == "scam":
        return "LIKELY SCAM" if score > 60 else "SUSPICIOUS"
    if category == "exploit":
        return "EXPLOITATIVE, NOT WORTH IT" if score > 60 else "SUSPICIOUS — check terms"
    if category == "bond":
        return "LEGAL GRAY AREA — see a lawyer"
    if category == "selfharm":
        return "DON'T DO IT — career + legal risk"
    if category == "unverifiable":
        return "UNVERIFIABLE — caution, not proof"
    if score <= 30:
        return "LIKELY GENUINE" if proof else "WORTH A LOOK — verify first"
    return "WORTH A LOOK — verify first"
