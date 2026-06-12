"""Parse spoken task-board commands (move, delete) and match tasks by name."""

from __future__ import annotations

import re
from typing import Any

STATUSES = ("backlog", "todo", "in_progress", "done")

STATUS_LABELS = {
    "backlog": "Backlog",
    "todo": "To Do",
    "in_progress": "In Progress",
    "done": "Done",
}

DELETE_RE = re.compile(
    r"^\s*(?:delete|remove|cancel|drop|clear|kill)\s+"
    r"(?:a\s+)?(?:the\s+)?(?:task\s+)?(?P<name>.+?)\s*$",
    re.I,
)

MOVE_RE = re.compile(
    r"^\s*(?:move|put|shift|send|place)\s+"
    r"(?:a\s+)?(?:the\s+)?(?:task\s+)?(?P<name>.+?)\s+"
    r"(?:to|into|in(?:to)?)\s+(?:the\s+)?(?P<dest>.+?)\s*$",
    re.I,
)

MARK_RE = re.compile(
    r"^\s*(?:mark\s+)?(?P<name>.+?)\s+as\s+(?P<dest>.+?)\s*$",
    re.I,
)

YES_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|confirm|correct|affirmative|do it|go ahead|"
    r"ok(?:ay)?|sure|please|proceed)\.?$",
    re.I,
)

NO_RE = re.compile(
    r"^(?:no|nope|nah|cancel(?:led)?|never mind|nevermind|don't|dont|stop|negative)\.?$",
    re.I,
)

ORDINALS = {
    "first": 0,
    "1st": 0,
    "one": 0,
    "1": 0,
    "second": 1,
    "2nd": 1,
    "two": 1,
    "2": 1,
    "third": 2,
    "3rd": 2,
    "three": 2,
    "3": 2,
    "fourth": 3,
    "4th": 3,
    "four": 3,
    "4": 3,
}


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_yes(text: str) -> bool:
    return bool(YES_RE.match(text.strip()))


def is_no(text: str) -> bool:
    return bool(NO_RE.match(text.strip()))


def parse_destination(text: str) -> str | None:
    """Map spoken column names to todo status values."""
    t = _normalize(text)
    t = re.sub(r"\b(?:bucket|column|list|sector|lane|pile|board)\b", "", t).strip()
    if not t:
        return None
    if "backlog" in t or t in ("later", "someday"):
        return "backlog"
    if "progress" in t or t in ("working", "started", "active"):
        return "in_progress"
    if any(word in t for word in ("done", "complete", "completed", "finished")):
        return "done"
    if re.search(r"\b(?:to\s*do|todo)\b", t) or t in ("do", "queue"):
        return "todo"
    return None


def _parse_command(transcript: str) -> dict[str, Any] | None:
    text = transcript.strip()
    if not text:
        return None

    match = DELETE_RE.match(text)
    if match:
        name = match.group("name").strip(" .,!?:;\"'")
        if name:
            return {"action": "delete", "query": name}

    for pattern in (MOVE_RE, MARK_RE):
        match = pattern.match(text)
        if not match:
            continue
        name = match.group("name").strip(" .,!?:;\"'")
        dest = parse_destination(match.group("dest"))
        if name and dest:
            return {"action": "move", "query": name, "target_status": dest}

    return None


def _score_match(query: str, title: str) -> float:
    q = _normalize(query)
    t = _normalize(title)
    if not q or not t:
        return 0.0
    if t == q:
        return 100.0
    if t.startswith(q):
        return 85.0
    if q.startswith(t):
        return 80.0
    if q in t:
        return 70.0
    if t in q:
        return 65.0

    q_words = set(q.split())
    t_words = set(t.split())
    if not q_words:
        return 0.0
    overlap = q_words & t_words
    if not overlap:
        return 0.0
    ratio = len(overlap) / len(q_words)
    if ratio >= 0.5:
        return 40.0 + ratio * 30.0
    return 0.0


def find_matches(query: str, todos: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for todo in todos:
        score = _score_match(query, todo.get("title", ""))
        if score >= 40.0:
            scored.append((score, todo))
    scored.sort(key=lambda item: (-item[0], item[1].get("title", "").lower()))
    if not scored:
        return []

    best = scored[0][0]
    threshold = max(40.0, best - 5.0)
    return [todo for score, todo in scored if score >= threshold][:limit]


def _resolve_pending(
    transcript: str,
    pending: dict[str, Any],
    todos: list[dict[str, Any]],
) -> dict[str, Any] | None:
    text = transcript.strip()
    if not text:
        return None

    candidate_ids = {c["id"] for c in pending.get("candidates", [])}
    pool = [t for t in todos if t["id"] in candidate_ids]
    if not pool:
        return None

    normalized = _normalize(text)
    if normalized in ORDINALS:
        idx = ORDINALS[normalized]
        if idx < len(pool):
            todo = pool[idx]
            return {"action": pending["action"], "todo": todo, "target_status": pending.get("target_status")}

    number_match = re.match(r"^(?:number\s+)?(\d+)$", normalized)
    if number_match:
        idx = int(number_match.group(1)) - 1
        if 0 <= idx < len(pool):
            todo = pool[idx]
            return {"action": pending["action"], "todo": todo, "target_status": pending.get("target_status")}

    matches = find_matches(text, pool, limit=1)
    if len(matches) == 1:
        return {"action": pending["action"], "todo": matches[0], "target_status": pending.get("target_status")}
    return None


def _public_todo(todo: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": todo["id"],
        "title": todo["title"],
        "status": todo["status"],
        "priority": todo.get("priority"),
        "due_date": todo.get("due_date"),
    }


def _confirm_message(action: str, todo: dict[str, Any], target_status: str | None = None) -> str:
    title = todo["title"]
    if action == "delete":
        return f'Delete "{title}". Say yes or no.'
    label = STATUS_LABELS.get(target_status or "", target_status or "")
    return f'Move "{title}" to {label}. Say yes or no.'


def _success_message(action: str, todo: dict[str, Any], target_status: str | None = None) -> str:
    title = todo["title"]
    if action == "delete":
        return f'Deleted "{title}".'
    label = STATUS_LABELS.get(target_status or "", target_status or "")
    return f'Moved "{title}" to {label}.'


def execute_confirm(confirm: dict[str, Any]) -> dict[str, Any]:
    """Build a successful executed response from a stored confirm payload."""
    action = confirm["action"]
    todo = confirm["todo"]
    target_status = confirm.get("target_status")
    return {
        "ok": True,
        "executed": True,
        "action": action,
        "todo": todo,
        "target_status": target_status,
        "message": _success_message(action, todo, target_status),
    }


def process_board_command(
    transcript: str,
    todos: list[dict[str, Any]],
    *,
    pending: dict[str, Any] | None = None,
    awaiting_confirm: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse a board voice command and resolve the target task."""
    text = transcript.strip()
    if not text:
        return {
            "ok": False,
            "error": "empty",
            "message": "I did not catch that.",
            "transcript": text,
        }

    if awaiting_confirm:
        if is_yes(text):
            return execute_confirm(awaiting_confirm)
        if is_no(text):
            return {
                "ok": True,
                "cancelled": True,
                "message": "Cancelled. Ready.",
                "transcript": text,
            }
        return {
            "ok": False,
            "error": "need_yes_no",
            "message": "Say yes or no.",
            "transcript": text,
            "awaiting_confirm": awaiting_confirm,
        }

    resolved: dict[str, Any] | None = None
    if pending:
        resolved = _resolve_pending(text, pending, todos)

    if not resolved:
        command = _parse_command(text)
        if not command:
            return {
                "ok": False,
                "error": "unrecognized",
                "message": (
                    'Say "move call dentist to in progress" or '
                    '"delete buy milk".'
                ),
                "transcript": text,
            }

        matches = find_matches(command["query"], todos)
        if not matches:
            return {
                "ok": False,
                "error": "not_found",
                "message": f'No task matching "{command["query"]}".',
                "transcript": text,
                "query": command["query"],
            }

        if len(matches) > 1:
            candidates = [_public_todo(t) for t in matches]
            names = ", ".join(f'"{c["title"]}"' for c in candidates[:3])
            extra = f" and {len(candidates) - 3} more" if len(candidates) > 3 else ""
            return {
                "ok": False,
                "error": "ambiguous",
                "message": f"Which task? {names}{extra}.",
                "transcript": text,
                "pending": {
                    "action": command["action"],
                    "target_status": command.get("target_status"),
                    "candidates": candidates,
                },
                "matches": candidates,
            }

        resolved = {
            "action": command["action"],
            "todo": matches[0],
            "target_status": command.get("target_status"),
        }

    action = resolved["action"]
    todo = resolved["todo"]
    target_status = resolved.get("target_status")
    public = _public_todo(todo)

    if action == "move":
        if not target_status:
            return {
                "ok": False,
                "error": "invalid_status",
                "message": "I could not tell which column to move it to.",
                "transcript": text,
            }
        if todo["status"] == target_status:
            label = STATUS_LABELS[target_status]
            return {
                "ok": True,
                "info": True,
                "message": f'"{todo["title"]}" is already in {label}. Ready.',
                "transcript": text,
            }

    confirm = {
        "action": action,
        "todo": public,
        "target_status": target_status,
    }
    return {
        "ok": True,
        "needs_confirm": True,
        "confirm": confirm,
        "message": _confirm_message(action, todo, target_status),
        "transcript": text,
    }
