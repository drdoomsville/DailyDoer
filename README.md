# Daily Doer

A local-first daily organizer with a dashboard landing page and full todo management.

- **Dashboard** (`/`) — urgent/high priority items, due today, tomorrow, and rest of week
- **All Todos** (`/todos`) — Kanban board (Backlog → To Do → In Progress → Done) with create, edit, delete, and drag-and-drop
- **Voice input** — speak a todo from the dashboard or All Todos page; fields are parsed automatically and follow-up questions are asked for anything missing (e.g. due date)

Python 3.10+ stdlib only. Data stored in `dailydoer.db` next to the app.

## Usage

```powershell
cd C:\Users\sonny\Projects\DailyDoer
python app.py
```

Open http://localhost:8780

```powershell
python app.py --port 9000
```

**Recommended:** use the launcher scripts so restarts are graceful and crashes auto-recover:

```powershell
.\run.ps1    # start (auto-restarts on crash, logs to dailydoer.log)
.\stop.ps1   # graceful stop (preferred over force-kill)
```

The server binds to `127.0.0.1` only. Keep the terminal running while you use it; Ctrl+C or `.\stop.ps1` stops it cleanly.

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Dashboard with stat cards, quick-add, and due-date groupings |
| `/todos` | Kanban board with backlog for long-term todos |
| Voice button | Speak a todo — browser speech recognition + server-side parsing |

## Voice todos

Click **Voice** on the dashboard or All Todos page. Speak naturally, for example:

- "Urgent call the dentist tomorrow"
- "Remind me to buy milk" → app asks when it's due
- "Someday learn Rust" → lands in backlog

The app extracts title, priority, due date, and status when it can. If the due date isn't mentioned, it asks follow-up questions (voice or typed). Say **"done"** or stay quiet for **10 seconds** to save automatically. Uses Chrome or Edge speech recognition locally in the browser — no API keys required.

## Todo fields

- **Title** — required
- **Description** — optional notes
- **Priority** — low, normal, high, urgent
- **Due date** — optional (`YYYY-MM-DD`)
- **Status** — backlog, todo, in_progress, done

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/dashboard` | Dashboard groupings and counts |
| GET | `/api/todos` | List todos (`?include_done=1`, `?status=todo`) |
| GET | `/api/todos/{id}` | Single todo |
| POST | `/api/todos` | Create todo |
| PUT | `/api/todos/{id}` | Update todo |
| PATCH | `/api/todos/{id}/move` | Move kanban column (`{"status": "..."}`) |
| DELETE | `/api/todos/{id}` | Delete todo |
| POST | `/api/voice/parse` | Parse speech transcript into todo fields (`transcript`, optional `draft`, `pending_field`) |
