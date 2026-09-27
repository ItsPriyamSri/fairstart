"""Interview prep: role topic maps, 7-day plans, tiny practice bank.

Deterministic and free. The chat layer serves plans + quiz questions from
here; the Gemini path may rephrase but never invents new topics.
"""
import re

TOPICS = {
    "python": ["Python basics (lists, dicts, comprehensions, OOP)", "DSA in Python (arrays, strings, hashmaps)",
               "Recursion + Big-O", "One mini-project you can explain end-to-end", "SQL basics + DBMS (joins, indexing)"],
    "web": ["HTML/CSS/JS fundamentals", "How the web works (HTTP, REST, auth)", "One framework deeply (Django/React)",
            "Git + deployment basics", "DBMS + one project demo"],
    "frontend": ["JavaScript deeply (closures, promises, async)", "React (hooks, state, props)", "CSS layout (flex/grid)",
                 "One polished project", "Basic DSA (arrays, strings)"],
    "data": ["Python (pandas, numpy)", "SQL (joins, group-by, windows)", "Statistics basics (mean/median, distributions)",
             "One dashboard/analysis project", "Excel + storytelling with data"],
    "java": ["Java OOP + collections", "DSA in Java", "DBMS + SQL", "Spring basics (if backend role)", "One project demo"],
    "general": ["DSA: arrays, strings, hashmaps first", "One language deeply", "DBMS + OS + CN theory basics",
                "Two projects you can defend line-by-line", "HR answers: intro, strengths, why us"],
}

ROLE_KEYS = [("python", r"python|django|flask|fastapi|backend"),
             ("frontend", r"front.?end|react|angular|vue|ui\b"),
             ("data", r"data|ml\b|machine learning|analyst|ai\b"),
             ("java", r"\bjava\b|spring"),
             ("web", r"web|full.?stack|node|mern|mern|php|laravel")]


def role_for(text: str) -> str:
    low = (text or "").lower()
    for role, pat in ROLE_KEYS:
        if re.search(pat, low):
            return role
    return "general"


def seven_day_plan(role: str, missing: list) -> list[str]:
    topics = TOPICS[role_for(role)]
    plan = [f"Day {i+1}: {t}" for i, t in enumerate(topics[:5])]
    if missing:
        plan.append(f"Day 6: close your top gap — {missing[0]}" + (f" (+{missing[1]})" if len(missing) > 1 else ""))
        plan.append("Day 7: mock round — explain your best project aloud in 5 minutes, then revise weak answers")
    else:
        plan += ["Day 6: timed mock — 2 DSA problems in 45 minutes, out loud",
                 "Day 7: revise HR answers + rest. Sleep beats cramming."]
    return plan


QBANK = {
    "python": [("What is a list comprehension? Give an example.", "A one-line way to build lists, e.g. [x*x for x in range(5)]. Say it, then write it."),
               ("List vs tuple?", "Lists are mutable, tuples immutable (and hashable). Mention when you'd pick each.")],
    "web": [("What happens when you type a URL and press enter?", "DNS → TCP → HTTP request → server → response → render. Breathe, then walk it in order."),
            ("GET vs POST?", "GET reads (params in URL), POST submits (body). Idempotency is the bonus word.")],
    "general": [("Explain Big-O with an example.", "How runtime grows with input; e.g. single loop = O(n). Say the tradeoff, not just the definition."),
                ("Tell me about yourself (2 minutes).", "Present → past project → why this role. Practice with a timer.")],
    "data": [("What does GROUP BY do?", "Groups rows sharing values so aggregates (COUNT/AVG) run per group. Give a sales-table example.")],
    "frontend": [("What is a closure?", "A function remembering its outer scope's variables. Give a counter example.")],
    "java": [("How does HashMap work?", "Array of buckets + hash + equals; collisions chain. Mention load factor.")],
}
