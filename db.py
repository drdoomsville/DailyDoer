"""SQLite persistence for Daily Doer todos."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "dailydoer.db"
_DB_LOCK = threading.Lock()

STATUSES = ("backlog", "todo", "in_progress", "done")
PRIORITIES = ("low", "normal", "high", "urgent")
STATUS_LABELS = {
    "backlog": "Backlog",
    "todo": "To Do",
    "in_progress": "In Progress",
    "done": "Done",
}
PRIORITY_LABELS = {
    "low": "Low",
    "normal": "Normal",
    "high": "High",
    "urgent": "Urgent",
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    with _DB_LOCK:
        with connect() as conn:
            conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'todo'
                    CHECK (status IN ('backlog', 'todo', 'in_progress', 'done')),
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
            CREATE INDEX IF NOT EXISTS idx_todos_due_date ON todos(due_date);
            CREATE INDEX IF NOT EXISTS idx_todos_priority ON todos(priority);
            """
            )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _week_end(today: date) -> date:
    """Sunday of the current calendar week."""
    return today + timedelta(days=(6 - today.weekday()))


def list_todos(
    *,
    status: str | None = None,
    include_done: bool = True,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if not include_done:
        clauses.append("status != 'done'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM todos
        {where}
        ORDER BY
            CASE priority
                WHEN 'urgent' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                ELSE 3
            END,
            due_date IS NULL,
            due_date ASC,
            sort_order ASC,
            id ASC
    """
    with _DB_LOCK:
        with connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_todo(todo_id: int) -> dict[str, Any] | None:
    with _DB_LOCK:
        with connect() as conn:
            row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return _row_to_dict(row) if row else None


def _next_sort_order(conn: sqlite3.Connection, status: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM todos WHERE status = ?",
        (status,),
    ).fetchone()
    return int(row[0])


def create_todo(
    *,
    title: str,
    description: str = "",
    priority: str = "normal",
    due_date: str | None = None,
    status: str = "todo",
) -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    if priority not in PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")

    now = _now()
    with _DB_LOCK:
        with connect() as conn:
            sort_order = _next_sort_order(conn, status)
            cur = conn.execute(
                """
                INSERT INTO todos (title, description, priority, due_date, status,
                                   sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    description.strip(),
                    priority,
                    due_date or None,
                    status,
                    sort_order,
                    now,
                    now,
                ),
            )
            todo_id = cur.lastrowid
            row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return _row_to_dict(row)


def update_todo(todo_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = {"title", "description", "priority", "due_date", "status", "sort_order"}
    updates: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "title":
            value = str(value).strip()
            if not value:
                raise ValueError("title is required")
        if key == "description":
            value = str(value).strip()
        if key == "priority" and value not in PRIORITIES:
            raise ValueError(f"invalid priority: {value}")
        if key == "status" and value not in STATUSES:
            raise ValueError(f"invalid status: {value}")
        if key == "due_date" and value == "":
            value = None
        updates[key] = value

    if not updates:
        return get_todo(todo_id)

    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [todo_id]

    with _DB_LOCK:
        with connect() as conn:
            cur = conn.execute(
                f"UPDATE todos SET {set_clause} WHERE id = ?",
                params,
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return _row_to_dict(row)


def move_todo(todo_id: int, *, status: str, sort_order: int | None = None) -> dict[str, Any] | None:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    fields: dict[str, Any] = {"status": status}
    if sort_order is not None:
        fields["sort_order"] = sort_order
    else:
        with _DB_LOCK:
            with connect() as conn:
                fields["sort_order"] = _next_sort_order(conn, status)
    return update_todo(todo_id, **fields)


def delete_todo(todo_id: int) -> bool:
    with _DB_LOCK:
        with connect() as conn:
            cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return cur.rowcount > 0


def _active_todos(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in todos if t["status"] != "done"]


def dashboard_data(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    week_end = _week_end(today)
    after_tomorrow = tomorrow + timedelta(days=1)

    todos = list_todos(include_done=False)
    active = _active_todos(todos)

    urgent_high = [
        t for t in active if t["priority"] in ("urgent", "high")
    ]

    def due_on(day: date) -> list[dict[str, Any]]:
        key = day.isoformat()
        return [t for t in active if t.get("due_date") == key]

    due_today = due_on(today)
    due_tomorrow = due_on(tomorrow)

    due_this_week: list[dict[str, Any]] = []
    if after_tomorrow <= week_end:
        for t in active:
            raw = t.get("due_date")
            if not raw:
                continue
            try:
                d = date.fromisoformat(raw)
            except ValueError:
                continue
            if after_tomorrow <= d <= week_end:
                due_this_week.append(t)

    by_status = {s: [t for t in todos if t["status"] == s] for s in STATUSES}

    return {
        "today": today.isoformat(),
        "tomorrow": tomorrow.isoformat(),
        "week_end": week_end.isoformat(),
        "counts": {
            "active": len(active),
            "urgent_high": len(urgent_high),
            "due_today": len(due_today),
            "due_tomorrow": len(due_tomorrow),
            "due_this_week": len(due_this_week),
            "backlog": len(by_status["backlog"]),
        },
        "urgent_high": urgent_high,
        "due_today": due_today,
        "due_tomorrow": due_tomorrow,
        "due_this_week": due_this_week,
        "by_status": by_status,
    }
