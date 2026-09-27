"""Resume handling: local-only PDF parse, skill extraction, job.Match scoring.

Privacy rule: the resume NEVER leaves this machine for SerpApi (queries use
derived keywords only). It is sent to Gemini only if a key is set AND the
user uploaded it here — stated on the upload form. Stored in local SQLite.
"""
import re

SKILLS = {
    "languages": ["python", "java", "javascript", "typescript", "c++", "c#", "go", "rust", "php", "ruby", "kotlin", "swift", "sql", "r ", "matlab", "scala", "dart"],
    "web": ["html", "css", "react", "angular", "vue", "django", "flask", "fastapi", "node", "express", "spring", "laravel", "next.js", "bootstrap", "tailwind", "rest api", "graphql"],
    "data": ["pandas", "numpy", "tensorflow", "pytorch", "scikit-learn", "power bi", "tableau", "excel", "spark", "hadoop", "machine learning", "deep learning", "nlp", "data analysis", "statistics"],
    "mobile": ["android", "ios", "flutter", "react native"],
    "devops": ["git", "docker", "kubernetes", "aws", "azure", "gcp", "linux", "jenkins", "ci/cd", "nginx"],
    "cs": ["dsa", "data structures", "algorithms", "dbms", "os", "operating systems", "computer networks", "oops", "system design"],
    "tools": ["figma", "photoshop", "postman", "jira", "selenium", "wordpress", "seo"],
}
ALL_SKILLS = sorted({s.strip() for bucket in SKILLS.values() for s in bucket})

MAX_RESUME_BYTES = 2 * 1024 * 1024


def parse_pdf(data: bytes) -> dict:
    """Extract text from a PDF resume. Honest errors, never silent garbage."""
    if not data or len(data) < 100:
        return {"ok": False, "error": "empty file"}
    if len(data) > MAX_RESUME_BYTES:
        return {"ok": False, "error": "PDF over 2MB — export a smaller one and retry"}
    if not data.lstrip().startswith(b"%PDF"):
        return {"ok": False, "error": "not a PDF file — upload your resume as PDF"}
    try:
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > 5:
            return {"ok": False, "error": "resume over 5 pages — trim it and retry"}
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return {"ok": False, "error": "could not read that PDF (scanned/image PDFs aren't supported — export text PDF)"}
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 200:
        return {"ok": False, "error": "almost no readable text (scanned image?) — upload a text-based PDF"}
    return {"ok": True, "text": text[:20000]}


def extract_skills(text: str) -> dict:
    """Skill hits + rough level from a resume text. Deterministic, explainable."""
    low = " " + (text or "").lower() + " "
    found = []
    for s in ALL_SKILLS:
        pat = r"(?<![a-z+#.])" + re.escape(s) + r"(?![a-z+#.])"
        if re.search(pat, low):
            found.append(s)
    yrs = [int(n) for n in re.findall(r"(\d+)\s*\+?\s*(?:years?|yrs?)\b.{0,30}(?:experience|work)", low)]
    senior = bool(re.search(r"\b(senior|lead|architect|manager|sde-?iii|5\+?\s*years?)\b", low))
    return {"skills": sorted(set(found)), "level": "experienced" if senior or (yrs and max(yrs) >= 3) else "fresher"}


def match(job_text: str, profile: dict) -> dict:
    """Match% between resume skills and JD skill signals. Separate axis from trust."""
    jd = extract_skills(job_text or "")["skills"]
    mine = set((profile or {}).get("skills", []))
    if not jd:
        return {"pct": None, "have": [], "missing": [], "note": "JD lists no detectable skills — match unknown"}
    have = sorted(s for s in jd if s in mine)
    missing = sorted(s for s in jd if s not in mine)
    pct = round(100 * len(have) / len(jd)) if jd else 0
    return {"pct": pct, "have": have, "missing": missing,
            "note": f"{len(have)}/{len(jd)} JD skills on your resume"}
