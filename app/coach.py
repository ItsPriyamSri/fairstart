"""Big-brother voice: warm openers, concrete cons, and grounded follow-up chat.

Every line here is deterministic and derived ONLY from the verdict's own
reasons, cues, and evidence. The Gemini path rephrases in the same voice but
may never add facts — the citation validator still applies to verdicts, and
chat replies must say "I don't know" when the answer isn't in the context.
"""
import re

OPENERS = {
    "scam": "Please don't send these people a single rupee — I know this offer looks exciting, especially when you're trying hard to get started, and that's exactly what they're counting on. Here's what I spotted in your message:",
    "exploit": "I get why this looks tempting — experience plus a certificate sounds like exactly what your resume needs. But look closer with me: this one takes more than it gives. Here's the honest breakup:",
    "bond": "Bonds scare everyone, and that's completely normal — even experienced people pause before signing one. I'm not a lawyer and this isn't legal advice, but here's how to read this before you sign anything:",
    "selfharm": "I hear you — when every job asks for experience you don't have, a shortcut feels reasonable. Someone who's watched this road end badly is asking you to hear them out first:",
    "unverifiable": "I couldn't find this company anywhere real, and that worries me — small companies can be great, but scammers love being ghosts. Treat this as guilty until proven innocent:",
    "clean": "Good news first — I checked this one properly and nothing smells off. Smart people still verify before they trust, so here's my honest read:",
}

CLOSERS = {
    "scam": "You're already smarter than most victims — you checked before paying. That's literally how you beat these guys. If they pressure you now, that's your final confirmation. 🤝",
    "exploit": "Your time is worth more than a PDF certificate. There are free internships that teach real skills — want help figuring out what to ask them before you decide? 🤝",
    "bond": "Never sign under pressure. Ask for 2 days, show it to a senior or a lawyer, and get every promise in writing. 🤝",
    "selfharm": "Real experience — even unpaid open-source work — beats a fake letter every time, because background checks WILL find the truth. Your career is worth more than a shortcut. 🤝",
    "unverifiable": "If they turn out legit, they'll happily prove it on a video call with an official email. Until then, protect your money and your documents. 🤝",
    "clean": "Looks genuinely promising — go for it, but keep the healthy habit: official emails, no payments, everything in writing. All the best! 🤝",
}

# cue -> concrete con (what the student actually loses), quoted from their message
CONS = {
    "fee": "Money out of YOUR pocket before day one — real employers pay you, never the reverse.",
    "upi": "Money sent over UPI/QR to a stranger is gone in seconds and almost never comes back.",
    "guarantee": "Nobody can guarantee a job or PPO in a WhatsApp message — that promise is the bait.",
    "chat_only": "No real interview, no office, no video call — so there's nobody to hold accountable later.",
    "gmail_hr": "A big company that hires over Gmail is like a bank operating from a tent — impersonation 101.",
    "task_lure": "Those early tiny payouts are pocket money to earn your trust; the big 'deposit' is the actual robbery.",
    "threat": "Real companies don't threaten legal action over chat — fear is how they stop you from thinking.",
    "pay_cert": "You'd pay for a certificate that recruiters can spot as worthless in 10 seconds — plus weeks of your time you'll never get back.",
    "commission_only": "You become their free salesperson; most students earn nothing and even the 'certificate' never arrives.",
    "unpaid_labor": "Months of real client work for free while they dangle a job that keeps moving — that's your semester gone.",
    "bond": "One signature could lock years of your career or cost lakhs to escape — read it like your future depends on it, because it does.",
    "sells_fakery": "A fake letter can get you fired years later, plus a police case — background checks (EPFO records, payslips) always catch up.",
}


def opener_for(category: str) -> str:
    return OPENERS.get(category, OPENERS["unverifiable"])


def closer_for(category: str) -> str:
    return CLOSERS.get(category, CLOSERS["unverifiable"])


def cons_for(cues: list[dict]) -> list[dict]:
    """Concrete cons with the student's own quoted words. Deduped, max 5."""
    out, seen = [], set()
    for c in cues:
        if c["cue"] in CONS and c["cue"] not in seen:
            seen.add(c["cue"])
            out.append({"cue": c.get("label", c["cue"]), "con": CONS[c["cue"]], "quote": c["quote"]})
        if len(out) >= 5:
            break
    return out


INTENTS = [
    ("why", re.compile(r"\b(why|reason|explain|how (do you know|did you)|what (makes|seems))", re.I)),
    ("next", re.compile(r"\b(what (should|do|next)|report|complain|refund|money (sent|paid|lost)|already paid)\b", re.I)),
    ("jobs", re.compile(r"\b(real|genuine|actual|safe|other|more)\b.{0,20}\b(jobs?|roles?|internships?|openings|opportunit)", re.I)),
    ("prep", re.compile(r"\b(interview|prepar|study plan|how (do|should) i (prepare|study)|7.day|week plan|roadmap)\b", re.I)),
    ("quiz", re.compile(r"\b(quiz|mock|test me|practice|question|ask me)\b", re.I)),
    ("pushback", re.compile(r"\b(but|however|friend|joined|received|got (paid|stipend)|looks? (real|genu|legit)|website|real (company|site))\b", re.I)),
    ("safe", re.compile(r"\b(safe|apply|join|trust|take (it|this)|should i)\b", re.I)),
]


def deterministic_reply(question: str, card: dict, thread: list) -> str:
    """Rule-based follow-up answer built ONLY from the card. Warm, honest, bounded."""
    from . import interview as _iv  # local import: coach stays import-light

    q = (question or "").lower()
    label, score = card.get("label", ""), card.get("score", 0)
    reasons = card.get("reasons", [])
    top = reasons[0].split("[")[0].strip() if reasons else "the signals I found"
    intent = next((name for name, pat in INTENTS if pat.search(q)), "fallback")
    if intent == "jobs":
        link = card.get("search_link") or "/search?role=fresher&location=India"
        role = card.get("search_role") or "entry-level"
        return (f"That's exactly the right instinct — don't mourn this one, replace it. I lined up real, verified {role} roles for you here: {link} "
                f"They're ranked safest-first with the same scam checks applied. Go get one you never have to doubt. 💪")
    if intent == "prep":
        role = card.get("prep_role") or _iv.role_for(card.get("description", ""))
        missing = ((card.get("match") or {}).get("missing") or [])[:3]
        plan = _iv.seven_day_plan(role, missing)
        return (f"Let's get you hired. Here's your 7-day {role} battle plan: " + " ".join(f"({p})" for p in plan) + " "
                f"One rule: explain everything OUT LOUD — interviews test communication, not just answers. Ask me for practice questions when ready. 📚")
    if intent == "quiz":
        role = card.get("prep_role") or _iv.role_for(card.get("description", ""))
        bank = _iv.QBANK.get(role, _iv.QBANK["general"])
        qi = len([m for m in thread if "Practice Q" in m.get("a", "")]) % len(bank)
        qq, qa = bank[qi]
        return (f"Practice Q ({role}): {qq} Take 60 seconds, answer aloud, then compare — model answer: {qa} "
                f"Say 'quiz' again for the next one. 🎯")
    if intent == "why":
        return (f"Great question — never take a score on faith, not even mine. The biggest red flag is: {top} "
                f"And it's not just one thing — I found {len(reasons)} such signals, all listed above with the exact quotes. "
                f"One oddity can be a mistake; {len(reasons)} of them together is a pattern. Does any particular reason feel unclear? Ask me about it.")
    if intent == "next":
        steps = card.get("next_steps", [])
        first = steps[0]["text"] if steps else "Don't pay anything."
        return (f"Here's your game plan, step by step. First: {first} "
                f"Second: keep screenshots of everything — chats, numbers, UPI IDs, emails. "
                f"Third: if you already paid or feel threatened, call cyber helpline 1930 right now and file at cybercrime.gov.in — the sooner, the better the chance. "
                f"And tell a friend or senior what happened; scams thrive on shame and silence. You're doing the right thing by asking. 💪")
    if intent == "pushback":
        return (f"I hear you — it's genuinely hard to walk away when it *looks* real, and scammers know exactly how to fake websites, offer letters, even video calls. "
                f"So let's test it instead of trusting it: ask them for (1) an interview on video, (2) an email from an official company domain, (3) the offer with zero payment. "
                f"A real company does all three happily; a scammer will dodge, rush you, or get angry. My verdict stays {label} ({score}/100) until they pass that test — "
                f"and honestly, their reaction to the test tells you everything. Want help drafting that reply to them?")
    if intent == "safe":
        verdict = "please don't — walk away" if score > 60 else "go slow and verify each of the points above first" if score > 30 else "looks fine to me — just keep everything in writing and never pay"
        return (f"Straight answer, friend to friend: {verdict}. My score is {score}/100 ({label}). "
                f"If you proceed, do it with eyes open: official email only, video interview, zero payments, and show the offer to a senior first. Deal?")
    return (f"I'm with you — let's dig into it. My overall read is {label} ({score}/100), based on {len(reasons)} signals I quoted above. "
            f"Ask me things like: *why is the fee a problem?*, *I already paid — what now?*, *but their website looks real?*, or *should I join?* — and I'll answer from the evidence, not guesses.")


def chat_prompt(question: str, card: dict, thread: list) -> str:
    """Grounding prompt for the LLM chat path: senior voice, evidence-only."""
    ev = card.get("evidence", {})
    return (
        "You are a caring Indian college senior acting as the student's personal guide — warm, direct, "
        "a little humor, emojis sparingly. Never announce roles or modes; just help. "
        "Use ONLY these verified facts — never invent companies, "
        "links, salaries, or incidents. If the answer isn't in the facts, say 'I honestly don't know — ask a placement cell senior'.\n"
        f"VERDICT: {card.get('label')} ({card.get('score')}/100). REASONS: {card.get('reasons')}. "
        f"CUES: {card.get('claims', {}).get('cues')}. EVIDENCE: {ev}. NEXT STEPS: {card.get('next_steps')}.\n"
        f"CHAT SO FAR: {thread[-6:]}\nJUNIOR ASKS: {question}\n"
        "Reply in 3-6 sentences, warm guide voice, end with one useful question back.")
