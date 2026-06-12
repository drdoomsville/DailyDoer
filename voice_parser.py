"""Parse spoken todo descriptions into structured fields with follow-up questions."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

PRIORITIES = ("low", "normal", "high", "urgent")
STATUSES = ("backlog", "todo", "in_progress", "done")

SKIP_WORDS = frozenset(
    {
        "skip",
        "none",
        "no",
        "nah",
        "nothing",
        "never",
        "no due date",
        "no date",
        "not needed",
        "doesn't matter",
        "doesnt matter",
        "don't know",
        "dont know",
        "normal",
        "default",
    }
)

DAY_NAMES = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

MONTH_NAMES = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

PRIORITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "urgent",
        re.compile(
            r"\b(?:urgent|asap|a\.s\.a\.p|immediately|critical|emergency)\b",
            re.I,
        ),
    ),
    (
        "high",
        re.compile(
            r"\b(?:high priority|high-priority|very important|important|high)\b",
            re.I,
        ),
    ),
    (
        "low",
        re.compile(r"\b(?:low priority|low-priority|whenever|no rush|low)\b", re.I),
    ),
]

STATUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "backlog",
        re.compile(
            r"\b(?:backlog|someday|some day|eventually|long term|long-term|later on|when i have time)\b",
            re.I,
        ),
    ),
    (
        "in_progress",
        re.compile(
            r"\b(?:in progress|in-progress|working on|started|already started)\b",
            re.I,
        ),
    ),
    ("done", re.compile(r"\b(?:done|completed|finished|complete)\b", re.I)),
    ("todo", re.compile(r"\b(?:to do|todo|need to|remember to|remind me to)\b", re.I)),
]

STRIP_PATTERNS = [
    re.compile(r"^\s*(?:add|create|new)\s+(?:a\s+)?(?:todo|task|reminder|objective)\s*(?:for|to)?\s*", re.I),
    re.compile(r"^\s*(?:i need to|i have to|i should|i must|remind me to|remember to)\s+", re.I),
    re.compile(r"^\s*(?:please\s+)?(?:can you\s+)?(?:add|create)\s+", re.I),
]

DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\btoday\b|\btonight\b|\bthis evening\b", re.I), "today"),
    (re.compile(r"\btomorrow\b|\btmrw\b", re.I), "tomorrow"),
    (re.compile(r"\bday after tomorrow\b", re.I), "day_after_tomorrow"),
    (re.compile(r"\bin\s+(\d+)\s+days?\b", re.I), "in_days"),
    (re.compile(r"\bnext\s+week\b", re.I), "next_week"),
    (re.compile(r"\bend\s+of\s+(?:the\s+)?week\b", re.I), "end_of_week"),
    (re.compile(r"\bthis\s+week\b", re.I), "this_week"),
    (
        re.compile(
            r"\b(?:next|this)\s+(monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thur|thurs|friday|fri|saturday|sat|sunday|sun)\b",
            re.I,
        ),
        "named_weekday",
    ),
    (
        re.compile(
            r"\b(?:on\s+)?(monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thur|thurs|friday|fri|saturday|sat|sunday|sun)\b",
            re.I,
        ),
        "weekday",
    ),
    (
        re.compile(
            r"\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|sept|october|oct|november|nov|december|dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?\b",
            re.I,
        ),
        "month_day",
    ),
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "iso"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"), "mdy"),
    (re.compile(r"\bdue\s+(?:on\s+)?(.+)$", re.I), "due_tail"),
]

QUESTIONS = {
    "title": "What should I call this todo?",
    "due_date": (
        "When is it due? Say today, tomorrow, a day of the week, a date, "
        "or say 'no due date'."
    ),
    "priority": "What priority — urgent, high, normal, or low? Say 'normal' to keep the default.",
    "status": (
        "Should this go in the backlog, to do, in progress, or done? "
        "Say 'to do' for a normal active task."
    ),
}


def _empty_draft() -> dict[str, Any]:
    return {
        "title": None,
        "description": "",
        "priority": None,
        "due_date": None,
        "status": None,
        "due_date_asked": False,
        "priority_asked": False,
        "status_asked": False,
        "due_date_declined": False,
    }


def _normalize_draft(raw: dict[str, Any] | None) -> dict[str, Any]:
    draft = _empty_draft()
    if not raw:
        return draft
    for key in draft:
        if key in raw:
            draft[key] = raw[key]
    return draft


def _clean_title(text: str) -> str:
    text = text.strip(" .,!?:;\"'")
    text = re.sub(r"\s+", " ", text)
    return text


def _next_weekday(from_day: date, weekday: int, *, force_next: bool = False) -> date:
    delta = (weekday - from_day.weekday()) % 7
    if delta == 0 and force_next:
        delta = 7
    elif delta == 0 and not force_next:
        return from_day
    if force_next and delta > 0:
        pass
    return from_day + timedelta(days=delta if delta else 7)


def _resolve_date_token(kind: str, match: re.Match[str], today: date) -> date | None:
    if kind == "today":
        return today
    if kind == "tomorrow":
        return today + timedelta(days=1)
    if kind == "day_after_tomorrow":
        return today + timedelta(days=2)
    if kind == "in_days":
        return today + timedelta(days=int(match.group(1)))
    if kind == "next_week":
        return today + timedelta(days=7)
    if kind == "end_of_week":
        return today + timedelta(days=(4 - today.weekday()) % 7) or today
    if kind == "this_week":
        return today + timedelta(days=(4 - today.weekday()) % 7) or today
    if kind in ("weekday", "named_weekday"):
        name = match.group(1).lower()
        weekday = DAY_NAMES.get(name)
        if weekday is None:
            return None
        force_next = kind == "named_weekday" and match.group(0).lower().startswith("next")
        return _next_weekday(today, weekday, force_next=force_next)
    if kind == "month_day":
        month_name = match.group(1).lower()
        day_num = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        month = MONTH_NAMES.get(month_name)
        if not month:
            return None
        try:
            d = date(year, month, day_num)
        except ValueError:
            return None
        if not match.group(3) and d < today:
            try:
                d = date(year + 1, month, day_num)
            except ValueError:
                return None
        return d
    if kind == "iso":
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    if kind == "mdy":
        month = int(match.group(1))
        day_num = int(match.group(2))
        year_raw = match.group(3)
        year = today.year if not year_raw else int(year_raw)
        if year < 100:
            year += 2000
        try:
            d = date(year, month, day_num)
        except ValueError:
            return None
        if not year_raw and d < today:
            try:
                d = date(year + 1, month, day_num)
            except ValueError:
                return None
        return d
    if kind == "due_tail":
        tail = match.group(1).strip()
        return extract_due_date(tail, today)
    return None


def extract_due_date(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    for pattern, kind in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        resolved = _resolve_date_token(kind, match, today)
        if resolved:
            return resolved
    return None


def extract_priority(text: str) -> str | None:
    for name, pattern in PRIORITY_PATTERNS:
        if pattern.search(text):
            return name
    return None


def extract_status(text: str) -> str | None:
    for name, pattern in STATUS_PATTERNS:
        if pattern.search(text):
            return name
    return None


def _strip_modifiers(text: str) -> str:
    result = text
    for pattern in STRIP_PATTERNS:
        result = pattern.sub("", result)
    for _, pattern in PRIORITY_PATTERNS:
        result = pattern.sub("", result)
    for _, pattern in STATUS_PATTERNS:
        result = pattern.sub("", result)
    for pattern, _ in DATE_PATTERNS:
        result = pattern.sub("", result)
    result = re.sub(r"\b(?:due|by|on|for)\s+(?:the\s+)?(?=\s|$)", " ", result, flags=re.I)
    result = re.sub(r"\s+", " ", result)
    return _clean_title(result)


def _is_skip(transcript: str) -> bool:
    normalized = transcript.strip().lower().rstrip(".!")
    return normalized in SKIP_WORDS or normalized.startswith("no due")


def _parse_priority_answer(transcript: str) -> str | None:
    if _is_skip(transcript):
        return "normal"
    pri = extract_priority(transcript)
    if pri:
        return pri
    normalized = transcript.strip().lower()
    for name in PRIORITIES:
        if name in normalized:
            return name
    return None


def _parse_status_answer(transcript: str) -> str | None:
    if _is_skip(transcript):
        return "todo"
    status = extract_status(transcript)
    if status:
        return status
    normalized = transcript.strip().lower()
    if "backlog" in normalized or "long term" in normalized:
        return "backlog"
    if "progress" in normalized:
        return "in_progress"
    if "done" in normalized or "complete" in normalized:
        return "done"
    if "to do" in normalized or normalized in ("todo", "active"):
        return "todo"
    return None


def _parse_due_answer(transcript: str, today: date) -> tuple[str | None, bool]:
    """Return (iso date or None, declined)."""
    if _is_skip(transcript) or "no due" in transcript.lower():
        return None, True
    due = extract_due_date(transcript, today)
    if due:
        return due.isoformat(), False
    return None, False


def _merge_description(draft: dict[str, Any], transcript: str) -> None:
    extra = transcript.strip()
    if not extra:
        return
    if draft["description"]:
        if extra not in draft["description"]:
            draft["description"] = f"{draft['description']} {extra}".strip()
    else:
        draft["description"] = extra


def _apply_full_parse(draft: dict[str, Any], transcript: str, today: date) -> None:
    due = extract_due_date(transcript, today)
    if due and draft["due_date"] is None and not draft["due_date_declined"]:
        draft["due_date"] = due.isoformat()

    pri = extract_priority(transcript)
    if pri and draft["priority"] is None:
        draft["priority"] = pri

    status = extract_status(transcript)
    if status and draft["status"] is None:
        draft["status"] = status

    title = _strip_modifiers(transcript)
    if title and not draft["title"]:
        draft["title"] = title[:200]
    elif title and draft["title"] and title.lower() != draft["title"].lower():
        _merge_description(draft, title)


def _apply_field_answer(
    draft: dict[str, Any],
    field: str,
    transcript: str,
    today: date,
) -> None:
    text = transcript.strip()
    if field == "title":
        title = _clean_title(text)
        if title:
            draft["title"] = title[:200]
        return

    if field == "due_date":
        draft["due_date_asked"] = True
        due, declined = _parse_due_answer(text, today)
        if declined:
            draft["due_date_declined"] = True
            draft["due_date"] = None
        elif due:
            draft["due_date"] = due
        return

    if field == "priority":
        draft["priority_asked"] = True
        pri = _parse_priority_answer(text)
        if pri:
            draft["priority"] = pri
        return

    if field == "status":
        draft["status_asked"] = True
        status = _parse_status_answer(text)
        if status:
            draft["status"] = status


def _next_missing_field(draft: dict[str, Any]) -> str | None:
    if not draft["title"]:
        return "title"
    if (
        draft["due_date"] is None
        and not draft["due_date_declined"]
        and not draft["due_date_asked"]
    ):
        return "due_date"
    return None


def _finalize_draft(draft: dict[str, Any]) -> dict[str, Any]:
    if draft["priority"] is None:
        draft["priority"] = "normal"
    if draft["status"] is None:
        draft["status"] = "todo"
    return draft


def _public_draft(draft: dict[str, Any]) -> dict[str, Any]:
    finalized = _finalize_draft(dict(draft))
    return {
        "title": finalized["title"],
        "description": finalized.get("description") or "",
        "priority": finalized["priority"],
        "due_date": finalized["due_date"],
        "status": finalized["status"],
    }


def process_voice(
    transcript: str,
    *,
    draft: dict[str, Any] | None = None,
    pending_field: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Parse speech into a todo draft and determine the next follow-up question."""
    today = today or date.today()
    draft = _normalize_draft(draft)
    text = transcript.strip()
    if not text:
        field = pending_field or _next_missing_field(draft)
        return {
            "draft": _public_draft(draft),
            "ready": bool(draft["title"]),
            "pending_field": field,
            "question": QUESTIONS.get(field) if field else None,
            "transcript": text,
        }

    if pending_field:
        _apply_field_answer(draft, pending_field, text, today)
    else:
        _apply_full_parse(draft, text, today)

    field = _next_missing_field(draft)
    ready = field is None and bool(draft["title"])

    return {
        "draft": _public_draft(draft) if ready else {
            "title": draft["title"],
            "description": draft.get("description") or "",
            "priority": draft["priority"],
            "due_date": draft["due_date"],
            "status": draft["status"],
        },
        "ready": ready,
        "pending_field": field,
        "question": QUESTIONS.get(field) if field else None,
        "transcript": text,
        "_state": draft,
    }


def finalize_for_save(draft: dict[str, Any] | None) -> dict[str, Any] | None:
    """Apply defaults and return a todo payload ready to persist."""
    normalized = _normalize_draft(draft)
    if not normalized["title"]:
        return None
    if normalized["due_date"] is None and not normalized["due_date_declined"]:
        normalized["due_date_declined"] = True
    return _public_draft(normalized)


def state_from_response(response: dict[str, Any]) -> dict[str, Any]:
    """Return internal draft state for the next request."""
    return response.get("_state") or _normalize_draft(response.get("draft"))
