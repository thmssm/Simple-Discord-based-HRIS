# Simple Discord-based HRIS

A lightweight Human Resources Information System powered by a Discord bot and web dashboard. Built with Python's standard library — no frameworks, no npm, no Docker.

## Features

- **Discord Bot** — voice session tracking, absence reporting (sick/leave/AFK), meeting schedules, daily check-ins, and automated summaries
- **Web Dashboard** — real-time attendance view, employee directory, calendar with schedules & holidays, reports, meeting history, and admin panel
- **AI-powered absence parsing** — team members report absences in natural language, parsed via LLM
- **SQLite-backed** — single-file database, zero configuration

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Discord (user-facing)                           │
│  #attendance  #hr-dashboard                      │
└──────────────┬───────────────────────────────────┘
               │ Discord API (websocket)
┌──────────────▼───────────────────────────────────┐
│  bot.py — Discord bot                            │
│  • Slash commands (/absen, /sakit, /meeting, …)   │
│  • Voice session auto-tracking                   │
│  • LLM-based absence parsing                     │
└──────────────┬───────────────────────────────────┘
               │ Shared SQLite DB
┌──────────────▼───────────────────────────────────┐
│  dashboard_api.py — HTTP server (port 8081)      │
│  • HTML/JSON endpoints                           │
│  • Login auth (SHA256+salt, session cookies)      │
│  • Turnstile CAPTCHA (optional)                  │
└──────────────┬───────────────────────────────────┘
               │ HTTP
┌──────────────▼───────────────────────────────────┐
│  Browser — Web Dashboard                         │
│  dashboard.html, admin.html, calendar.html, …    │
└──────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
- Python 3.11+
- Discord Bot Token ([create one](https://discord.com/developers/applications))
- (Optional) DeepSeek or OpenAI API key for AI absence parsing

### Setup

```bash
# Clone
git clone https://github.com/thmssm/Simple-Discord-based-HRIS.git
cd Simple-Discord-based-HRIS

# Configure
cp .env.example .env
# Edit .env with your tokens

# Run the dashboard (standalone, no Discord required)
python3 dashboard_api.py

# Run with Discord bot
python3 bot.py
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | For bot | — | Discord bot token |
| `DEEPSEEK_API_KEY` | For AI features | — | LLM API key for absence parsing |
| `TURNSTILE_SECRET_KEY` | Optional | — | Cloudflare Turnstile secret |
| `HRBOT_DB_PATH` | No | `hr.db` | SQLite database path |
| `HRBOT_LOG_PATH` | No | `bot.log` | Log file path |
| `HRBOT_SERVICE` | No | `hr-bot.service` | systemd service name (watchdog) |

## Web Dashboard Pages

| Route | Page | Description |
|-------|------|-------------|
| `/login` | Login | Auth with optional Turnstile CAPTCHA |
| `/` | Dashboard | Absences, voice sessions, upcoming meetings |
| `/absences` | Absences | Absence log with date filtering |
| `/people` | People | Employee directory with search |
| `/people/{id}` | Person Detail | Individual attendance profile |
| `/calendar` | Calendar | Holidays + recurring schedules |
| `/reports` | Reports | Daily attendance summaries |
| `/attendance-history` | History | Historical attendance data |
| `/admin` | Admin | Member management |

## Tech Stack

- **Backend**: Python 3 (`http.server`, `sqlite3`)
- **Bot**: `discord.py`
- **Frontend**: Vanilla HTML/CSS/JS (no frameworks)
- **Auth**: SHA256 + salt, session cookies (24h)
- **CAPTCHA**: Cloudflare Turnstile (optional)
- **Database**: SQLite (WAL mode)

## License

MIT
