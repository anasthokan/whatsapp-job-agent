import re

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "\uFE0F\u200D"
    "]+"
)

PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?966|00966|0)?5\d{8}(?!\d)|(?<!\d)\+?\d{10,15}(?!\d)"
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
LOCATION_RE = re.compile(r"location\s*[:：\-]\s*(.+)", re.I)
LOCATION_FOR_RE = re.compile(
    r"\bfor\s+((?:(?!\bfor\b)[A-Za-z .'\-]){1,40}?)\s+location\b", re.I
)
COMPANY_RE = re.compile(r"company\s*[:：]\s*(.+)", re.I)
DURATION_RE = re.compile(r"duration\s*[:：]\s*(.+)", re.I)
POSITIONS_RE = re.compile(r"(\d+)\s*\+?\s*positions?\b", re.I)
SALARY_RE = re.compile(r"salary\s*[:：]\s*(.+)", re.I)
HIRING_TITLE_RE = re.compile(r"(?:hiring|vacancy)\s*\|\s*(.+)", re.I)
LOOKING_FOR_RE = re.compile(
    r"looking\s+for\s+(.+?)(?:\s+for\s+\S.{0,60}?location|\s+[–—-]|\s+\d+\s+positions\b|$)",
    re.I,
)

SECTION_HEADS = {
    "responsibilities": ("key responsibilities", "responsibilities", "duties"),
    "requirements": ("requirements", "requirement", "required documents", "required document"),
}

STRONG_HINTS = (
    "looking for",
    "we are hiring",
    "hiring |",
    "vacancy",
    "vacancies",
    "send your",
    "required documents",
    "job title",
    "open position",
    "job opening",
)
HINTS = (
    "hiring",
    "position",
    "positions",
    "salary",
    "location",
    "experience",
    "cv",
    "resume",
    "iqama",
    "iquama",
    "ajeer",
    "apply",
    "candidate",
    "vacancy",
)
ARABIC_HINTS = ("مطلوب", "وظيفة", "وظائف", "للتواصل", "شاغر", "خبرة", "الراتب")
GREETING_PREFIXES = ("dear ", "assalam", "السلام", "hi ", "hello ")


def clean_inline(value: str) -> str:
    value = EMOJI_RE.sub("", value or "")
    value = value.replace("*", "").replace("_", "")
    value = re.sub(r"\s+", " ", value).strip(" \t|–—:-")
    return value.strip()


def looks_like_job(text: str) -> bool:
    body = (text or "").strip()
    if len(body) < 25:
        return False
    lowered = body.lower()
    if any(hint in lowered for hint in STRONG_HINTS):
        return True
    if any(hint in body for hint in ARABIC_HINTS):
        return True
    score = sum(1 for hint in HINTS if hint in lowered)
    return score >= 2


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.replace("\r\n", "\n").split("\n")]


def _section_map(lines: list[str]) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in lines:
        heading = clean_inline(line).lower().rstrip(":")
        matched = None
        for key, names in SECTION_HEADS.items():
            if heading in names:
                matched = key
                break
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        if current and line.strip():
            sections[current].append(clean_inline(line))
    return {key: "\n".join(parts).strip() for key, parts in sections.items()}


def _title(text: str, lines: list[str]) -> str:
    for line in lines:
        match = HIRING_TITLE_RE.search(clean_inline(line))
        if match:
            title = clean_inline(match.group(1))
            if title:
                return title[:512]
    for line in lines:
        raw = line.strip()
        if raw.startswith("*") and raw.endswith("*") and len(raw) > 2:
            title = clean_inline(raw)
            if title and not title.lower().startswith(tuple(SECTION_HEADS["requirements"])):
                return title[:512]
    flat = re.sub(r"\s+", " ", text)
    match = LOOKING_FOR_RE.search(flat)
    if match:
        title = clean_inline(match.group(1))
        title = re.sub(r"\s+for\s+.+$", "", title, flags=re.I).strip()
        if title:
            return title[:512]
    for line in lines:
        title = clean_inline(line)
        if not title:
            continue
        if title.lower().startswith(GREETING_PREFIXES):
            continue
        if title.lower().rstrip(":") in {
            name for names in SECTION_HEADS.values() for name in names
        }:
            continue
        return title[:512]
    return ""


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    return clean_inline(match.group(1))[:512]


YEARS_RE = re.compile(
    r"(?:minimum of\s*)?(\d{1,2})\s*\+?\s*(?:[-–]\s*\d{1,2}\s*)?years?",
    re.I,
)
SALARY_RANGE_RE = re.compile(
    r"(\d[\d,]{2,})\s*(?:to|[-–])\s*(\d[\d,]{2,})\s*(SAR|SR|USD|AED)?",
    re.I,
)
SKILL_TERMS = (
    "Python", "Java", "JavaScript", "TypeScript", "SQL", "Excel", "SAP",
    "Salesforce", "Kubernetes", "Docker", "AWS", "Azure", "GCP", "React",
    "Angular", "Node.js", ".NET", "C#", "PMP", "PRINCE2", "Agile", "Scrum",
    "Jira", "Power BI", "ISO 27001", "NIST", "SOC 2", "PCI DSS", "COBIT",
    "Machine Learning", "NLP", "Generative AI", "Cybersecurity", "Linux",
)
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def _years(text: str) -> int | None:
    match = YEARS_RE.search(text)
    if not match:
        return None
    years = int(match.group(1))
    if years > 40:
        return None
    return years


def _experience_level(title: str, years: int | None, text: str) -> str:
    blob = f"{title} {text[:400]}".lower()
    if re.search(r"\bintern(ship)?\b", blob):
        return "Intern/New Grad"
    if re.search(r"\b(head of|director|chief|vice president|\bvp\b|cxo)\b", blob):
        return "Director/Executive"
    if re.search(r"\b(staff|principal|architect|tech lead)\b", blob):
        return "Lead/Staff"
    if "senior" in blob or (years is not None and years >= 8):
        return "Senior Level"
    if years is not None and years >= 3:
        return "Mid Level"
    if years is not None:
        return "Entry Level"
    return "unknown"


def _work_model(text: str, location: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(remote|work from home|wfh)\b", lowered):
        return "remote"
    if "hybrid" in lowered:
        return "hybrid"
    if location or re.search(r"\b(on-?site|office)\b", lowered):
        return "onsite"
    return "unknown"


def _job_type(text: str, duration: str) -> str:
    lowered = f"{text} {duration}".lower()
    if "intern" in lowered:
        return "internship"
    if re.search(r"\bpart[- ]?time\b", lowered):
        return "parttime"
    if duration or re.search(r"\b(contract|temporary|freelance)\b", lowered):
        return "contract"
    return "fulltime"


def _skills(text: str) -> list[str]:
    found = []
    for term in SKILL_TERMS:
        pattern = re.escape(term).replace(r"\ ", r"\s+")
        if re.search(rf"(?<!\w){pattern}(?!\w)", text, re.I):
            found.append(term)
    return found


def _salary(text: str) -> dict:
    match = SALARY_RANGE_RE.search(text)
    if not match:
        return {"salary_min": None, "salary_max": None, "currency": "", "compensation_period": ""}
    low = int(match.group(1).replace(",", ""))
    high = int(match.group(2).replace(",", ""))
    currency = (match.group(3) or "").upper()
    if currency == "SR":
        currency = "SAR"
    period = ""
    lowered = text.lower()
    if "per month" in lowered or "monthly" in lowered or "/month" in lowered:
        period = "monthly"
    elif "per year" in lowered or "annual" in lowered or "/year" in lowered:
        period = "annual"
    return {
        "salary_min": low,
        "salary_max": high,
        "currency": currency[:3],
        "compensation_period": period,
    }


def _state_and_location(location: str) -> tuple[str, str]:
    cleaned = clean_inline(location)
    if not cleaned:
        return "Saudi Arabia", "Saudi Arabia"
    state = cleaned.split(",")[0].strip() or "Saudi Arabia"
    if "saudi" not in cleaned.lower():
        cleaned = f"{cleaned}, Saudi Arabia"
    return state[:255], cleaned[:512]


def parse_job(text: str) -> dict | None:
    body = (text or "").strip()
    if not looks_like_job(body):
        return None
    lines = _lines(body)
    sections = _section_map(lines)
    phones = []
    for match in PHONE_RE.finditer(body):
        number = re.sub(r"[^\d+]", "", match.group(0))
        if number not in phones and len(re.sub(r"\D", "", number)) >= 10:
            phones.append(number)
    email_match = EMAIL_RE.search(body)
    location = _first(LOCATION_RE, body) or _first(LOCATION_FOR_RE, body)
    if location.lower().endswith("location"):
        location = clean_inline(re.sub(r"\s+location$", "", location, flags=re.I))
    positions = ""
    positions_match = POSITIONS_RE.search(body)
    if positions_match:
        positions = positions_match.group(1)
    requirements = sections.get("requirements", "")
    if not requirements:
        requirements = _first(
            re.compile(r"required documents?\s*[:：]\s*(.+)", re.I), body
        )
    title = _title(body, lines)
    duration = _first(DURATION_RE, body)[:128]
    state, full_location = _state_and_location(location)
    years = _years(body)
    lowered = body.lower()
    saudi_required = "yes" if re.search(
        r"saudi national only|saudi only|only saudi|سعودي فقط", lowered
    ) else "no"
    saudi_preferred = 1 if re.search(r"saudi (national )?preferred|يفضل سعودي", lowered) else 0
    if re.search(r"\bvisa (provided|sponsorship)|sponsorship available\b", lowered):
        visa = "yes"
    elif re.search(r"\bno visa\b|visa not provided", lowered):
        visa = "no"
    else:
        visa = "unknown"
    salary = _salary(body)
    return {
        "title": title,
        "location": full_location,
        "state": state,
        "company": _first(COMPANY_RE, body)[:255],
        "contact_phone": (phones[0] if phones else "")[:64],
        "contact_email": (email_match.group(0) if email_match else "")[:254],
        "positions": positions[:64],
        "duration": duration,
        "salary": _first(SALARY_RE, body)[:128],
        "requirements": requirements,
        "responsibilities": sections.get("responsibilities", ""),
        "raw_text": body,
        "skills": _skills(body),
        "job_type": _job_type(body, duration),
        "work_model": _work_model(body, location),
        "experience_level": _experience_level(title, years, body),
        "years_experience": years,
        "visa_sponsorship": visa,
        "clearance_required": "unknown",
        "saudi_national_required": saudi_required,
        "saudi_national_preferred": saudi_preferred,
        "sponsors_work_visa": 1 if visa == "yes" else 0,
        "title_ar": title[:512] if ARABIC_RE.search(title) else "",
        "description_ar": body if ARABIC_RE.search(body) else "",
        **salary,
    }
