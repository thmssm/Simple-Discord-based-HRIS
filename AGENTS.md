# HRIS Agent Guide

This file helps AI coding agents understand the HRIS codebase structure and conventions.

## System Overview

Single-file Python HTTP server (`dashboard_api.py`) + Discord bot (`bot.py`). All HTML pages are server-rendered via `open().read()` and injected into a navigation wrapper. No framework dependencies — pure stdlib.

## Key Files

| File | Purpose |
|------|---------|
| `dashboard_api.py` | Main HTTP server (~1400 lines): auth, API, HTML serving |
| `bot.py` | Discord bot (~900 lines): slash commands, voice tracking, LLM parsing |
| `dashboard.html` | Main dashboard page — absences, voice, meetings cards |
| `login.html` | Login page with Turnstile CAPTCHA widget |
| `admin.html` | Member CRUD management |
| `people.html` | Employee directory list |
| `person.html` | Per-employee attendance detail page |
| `calendar.html` | Monthly calendar with holidays & schedule grid |
| `reports.html` | Attendance reports |
| `attendance-history.html` | Historical attendance browser |
| `absences.html` | Absence log viewer |
| `static/nav.css` | Navigation rail + drawer CSS (M3-inspired responsive) |
| `static/nav.js` | Navigation drawer toggle + responsive behavior |
| `watchdog.py` | Health check script (systemd heartbeat monitor) |
| `parse_absence.py` | CLI tool for testing LLM absence parsing |

## Architecture

### Request Flow (Dashboard)

```
Browser → HTTP → dashboard_api.py (port 8081)
  ├── GET /login → login.html ✕ (no auth)
  ├── GET /api/* → JSON response ✕ (no auth for read-only APIs)
  ├── GET / → _nav_wrapper(dashboard.html) ✓ (auth required)
  ├── POST /api/login → validate credentials → set session cookie
  └── GET /api/logout → delete session → redirect to /login
```

### Auth System

- Passwords stored in `credentials` table: `SHA256(salt:password)` → `salt:hash`
- Sessions: 32-char hex token, 24h expiry, HttpOnly cookie (Secure in production)
- Login rate limiting: max attempts tracked per IP, cleaned hourly
- All HTML pages (except `/login`) redirect to login if no valid session cookie
- Read-only JSON APIs (`/api/today`, `/api/person/*`, `/api/calendar`, etc.) are auth-bypassed for script access

### Database Schema

Tables: `credentials`, `members`, `absences`, `voice_sessions`, `meeting_schedules`, `meeting_history`, `holidays`, `member_roles`, `sessions`, `settings`, `login_attempts`, `bot_heartbeat`

Key relationships:
- `members.discord_id` → foreign key across `absences`, `voice_sessions`, `meeting_history`
- `members.division_id` → `divisions.id`
- Meetings auto-generated daily from `meeting_schedules` (recurring by day_of_week)
- Absences support date ranges (`start_date` to `end_date`)

## Conventions

### Timezone

All times stored in UTC. WIB (UTC+7) conversion happens client-side:
- `fmtTime(utc_hh_mm_ss)` for HH:MM display (meeting times)
- `new Date(dt+'Z').toLocaleTimeString('id-ID', …)` for full datetime (voice sessions)

### Nav Wrapper Pattern

HTML pages are **partials** — they are wrapped by `_nav_wrapper()` which:
1. Extracts `<head>` content into `__HEAD_CONTENT__`
2. Strips `</body>` and everything after
3. Injects into `NAV_HTML` template at `__BODY_CONTENT__`

Pages must NOT have `<head>`, `<body>`, or `</body>` tags — they're provided by the wrapper.
Every `id` in the page content must be unique (wrapper doesn't deduplicate).

### API Response Shape

`/api/today` example:
```json
{
  "absences": [{"discord_id": "...", "type": "sick", "note": "..."}],
  "active_voice": [{"user_id": "...", "user_name": "...", "channel_name": "..."}],
  "voice_today": [{"user_id": "...", "user_name": "...", "duration_minutes": 45}],
  "upcoming_meetings": [{"name": "...", "start_time": "01:00:00", "end_time": "02:00:00"}],
  "stats": {"total_voice_sessions": 12, "active_now": 3}
}
```

## Common Pitfalls

- **No `return;` at global scope** in inline `<script>` — wrap all logic in a function
- **`dict.get("key", default)` doesn't catch `None`** — use `or` instead (LLM JSON returns `null` → Python `None`)
- **`sqlite3.Row` has no `.get()`** — use `row["key"]`
- **Turnstile disabled by default** in this repo — set TURNSTILE_SECRET_KEY in .env to activate
- **Logout route must be in do_GET** (not just do_POST) for `<a href>` links
- **All API URLs are relative** (`var API=''`) so they work on any origin
