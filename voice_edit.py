"""Parse spoken edit commands for existing tasks."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from voice_board import STATUS_LABELS, find_matches, is_no, is_yes
from voice_parser import PRIORITIES, extract_due_date

EDIT_START_RE = re.compile(
    r"^\s*(?:edit|update|change)\s+(?:the\s+)?(?:task\s+)?(?P<name>.+?)\s*$",
    re.I,
)

PRIORITY_RE = re.compile(
    r"^\s*(?:set|change)\s+(?:the\s+)?(?:priority|status)\s+to\s+"
    r"(?P<pri>low|normal|high|urgent)\s*$",
    re.I,
)

DUE_RE = re.compile(
    r"^\s*(?:set|change)\s+(?:the\s+)?due(?:\s+date)?\s+(?:to\s+)?(?P<due>.+?)\s*$",
    re.I,
)

CLEAR_DUE_RE = re.compile(
    r"^\s*(?:clear|remove|delete)\s+(?:the\s+)?due(?:\s+date)?\s*$",
    re.I,
)

SAVE_RE = re.compile(
    r"^\s*(?:save(?:\s+changes)?|apply(?:\s+changes)?)\s*$",
    re.I,
)


def _public_todo(todo: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": todo["id"],
        "title": todo["title"],
        "status": todo["status"],
        "priority": todo.get("priority") or "normal",
        "due_date": todo.get("due_date"),
        "description": todo.get("description") or "",
    }


def _session_from_todo(todo: dict[str, Any]) -> dict[str, Any]:
    return {
        "todo": _public_todo(todo),
        "changes": {},
    }


def _merged_fields(session: dict[str, Any]) -> dict[str, Any]:
    todo = session["todo"]
    changes = session.get("changes") or {}
    return {
        "title": todo["title"],
        "priority": changes.get("priority", todo.get("priority") or "normal"),
        "due_date": changes["due_date"] if "due_date" in changes else todo.get("due_date"),
        "status": changes.get("status", todo.get("status") or "todo"),
        "description": changes.get("description", todo.get("description") or ""),
    }


def _save_summary(session: dict[str, Any]) -> str:
    fields = _merged_fields(session)
    pri = fields["priority"].title()
    due = fields["due_date"] or "no due date"
    return f'Save changes to "{fields["title"]}": priority {pri}, due {due}. Say yes or no.'


def process_edit_command(
    transcript: str,
    todos: list[dict[str, Any]],
    *,
    edit_session: dict[str, Any] | None = None,
    awaiting_save: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Parse edit voice commands."""
    today = today or date.today()
    text = transcript.strip()
    if not text:
        return {"ok": False, "error": "empty", "message": "I did not catch that."}

    if awaiting_save:
        if is_yes(text):
            return {
                "ok": True,
                "save": True,
                "edit_session": awaiting_save,
                "fields": _merged_fields(awaiting_save),
                "message": "Changes saved.",
            }
        if is_no(text):
            return {
                "ok": True,
                "cancelled": True,
                "message": "Changes not saved.",
            }
        return {
            "ok": False,
            "error": "need_yes_no",
            "message": "Say yes or no.",
            "awaiting_save": awaiting_save,
        }

    if edit_session:
        if SAVE_RE.match(text):
            if not edit_session.get("changes"):
                return {
                    "ok": True,
                    "info": True,
                    "edit_session": edit_session,
                    "message": "No changes to save.",
                }
            return {
                "ok": True,
                "needs_save_confirm": True,
                "awaiting_save": edit_session,
                "message": _save_summary(edit_session),
            }

        pri_match = PRIORITY_RE.match(text)
        if pri_match:
            pri = pri_match.group("pri").lower()
            if pri not in PRIORITIES:
                return {"ok": False, "message": "Invalid priority."}
            session = dict(edit_session)
            changes = dict(session.get("changes") or {})
            changes["priority"] = pri
            session["changes"] = changes
            return {
                "ok": True,
                "edit_session": session,
                "message": f"Priority set to {pri.title()}. Say save when ready.",
            }

        if CLEAR_DUE_RE.match(text):
            session = dict(edit_session)
            changes = dict(session.get("changes") or {})
            changes["due_date"] = None
            session["changes"] = changes
            return {
                "ok": True,
                "edit_session": session,
                "message": "Due date cleared. Say save when ready.",
            }

        due_match = DUE_RE.match(text)
        if due_match:
            due_text = due_match.group("due").strip()
            if due_text.lower() in ("none", "no due date", "clear"):
                session = dict(edit_session)
                changes = dict(session.get("changes") or {})
                changes["due_date"] = None
                session["changes"] = changes
                return {
                    "ok": True,
                    "edit_session": session,
                    "message": "Due date cleared. Say save when ready.",
                }
            parsed = extract_due_date(due_text, today)
            if not parsed:
                return {
                    "ok": False,
                    "edit_session": edit_session,
                    "message": "I could not understand that date.",
                }
            session = dict(edit_session)
            changes = dict(session.get("changes") or {})
            changes["due_date"] = parsed.isoformat()
            session["changes"] = changes
            return {
                "ok": True,
                "edit_session": session,
                "message": f"Due date set to {parsed.isoformat()}. Say save when ready.",
            }

        return {
            "ok": False,
            "edit_session": edit_session,
            "message": (
                'Say "set priority to urgent", "set due date to tomorrow", or "save".'
            ),
        }

    match = EDIT_START_RE.match(text)
    if not match:
        return {
            "ok": False,
            "error": "unrecognized",
            "message": 'Say "edit buy milk" to change a task.',
        }

    query = match.group("name").strip(" .,!?:;\"'")
    matches = find_matches(query, todos)
    if not matches:
        return {
            "ok": False,
            "error": "not_found",
            "message": f'No task matching "{query}".',
        }
    if len(matches) > 1:
        names = ", ".join(f'"{t["title"]}"' for t in matches[:3])
        return {
            "ok": False,
            "error": "ambiguous",
            "message": f"Which task? {names}.",
            "pending_edit": query,
        }

    todo = matches[0]
    session = _session_from_todo(todo)
    pri = (todo.get("priority") or "normal").title()
    due = todo.get("due_date") or "no due date"
    return {
        "ok": True,
        "edit_session": session,
        "message": (
            f'Editing "{todo["title"]}". Priority {pri}, due {due}. '
            'Say set priority to urgent or set due date to tomorrow. Say save when ready.'
        ),
    }
