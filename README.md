# YourOrg HR Dashboard

HR attendance management system for YourOrg — Discord bot + web dashboard.

## Overview

Tracks employee attendance via Discord voice activity, manages meeting schedules, handles absence logging, and provides a web dashboard for HR operations.

### Features

**Discord Bot (Ucchi)**
- Natural language meeting creation (Indonesian + English)
- Auto-generates recurring meeting instances from schedules
- Tracks voice channel join/leave for attendance
- Parses absence messages from `#absensi` channel
- Name/nickname-based invite resolution (no @mention needed)

**Web Dashboard**
- Today's overview: active voice, upcoming meetings, absences
- Attendance tab: who's present/late/missing per day
- Schedules tab: create/update/delete recurring meetings with member assignment
- History tab: concluded meetings with attendee analysis
- Calendar: monthly view with meeting dots, holiday highlighting, schedule preview
- Attendance History: per-member daily status (Present/Late/Missing/Holiday/Weekend)
- Absence Log: all absence records with raw Discord messages
- Admin: member management with nickname support
- Login with Turnstile bot protection + rate limiting

## Architecture

```
discord.py bot  →  SQLite (WAL)  ←  http.server API  →  nginx  →  Cloudflare  →  your-domain.com
```

- **Bot**: `bot.py` — Discord client, handles @ucchi commands and voice tracking
- **API**: `dashboard_api.py` — serves all pages and REST endpoints on port 8081
- **DB**: `hr.db` — SQLite with WAL mode, used by both bot and API
- **Frontend**: Static HTML/CSS/JS pages, all inline (no build step)

## Setup

### Requirements

- Python 3.11+
- Discord bot with `message_content`, `members`, `voice_states` intents
- Cloudflare Turnstile (free)

### Environment Variables

```bash
export DISCORD_BOT_TOKEN="your_discord_bot_token"
export DEEPSEEK_API_KEY="your_deepseek_api_key"
export TURNSTILE_SECRET_KEY="your_turnstile_secret"
```

### Installation

```bash
# Clone
git clone https://github.com/YOUR_USER/yourorg-hr-dashboard.git
cd yourorg-hr-dashboard

# Create venv
python3 -m venv .venv && source .venv/bin/activate
pip install discord.py

# Initialize database
python3 -c "
import sqlite3
db = sqlite3.connect('hr.db')
db.execute('PRAGMA journal_mode=WAL')
# Tables are auto-created on first bot run
db.close()
"

# Start services
python3 bot.py &
python3 dashboard_api.py &
```

### Systemd (production)

```ini
# /etc/systemd/system/hr-bot.service
[Unit]
Description=YourOrg HR Discord Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=.
EnvironmentFile=./.env
ExecStart=./.venv/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### Nginx

```nginx
server {
    server_name your-domain.com;
    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header Cache-Control "no-store";
    }
}
```

### Default Login

The first admin account is created by running:
```python
python3 -c "
import sqlite3, hashlib, secrets
s = secrets.token_hex(16)
h = hashlib.sha256(f'{s}:YOUR_PASSWORD'.encode()).hexdigest()
db = sqlite3.connect('hr.db')
db.execute('CREATE TABLE IF NOT EXISTS credentials (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, created_at DEFAULT CURRENT_TIMESTAMP)')
db.execute('INSERT INTO credentials (username, password_hash) VALUES (?,?)', ('admin', f'{s}:{h}'))
db.commit()
"
```

## Database Tables

| Table | Purpose |
|-------|---------|
| `members` | Employee records (name, discord_id, nickname, role, division) |
| `meetings` | Meeting instances (one-time + auto-generated) |
| `meeting_schedules` | Recurring schedule templates |
| `schedule_members` | Member assignment to schedules |
| `meeting_invites` | Per-meeting invite list |
| `voice_sessions` | Discord voice join/leave events |
| `absences` | Parsed absence records from #absensi |
| `message_log` | Raw Discord messages in #absensi |
| `holidays` | Company holiday calendar |
| `credentials` | Hashed login credentials |
| `sessions` | Active login sessions |
| `login_attempts` | Rate limiting audit log |

## License

Private — YourOrg internal use.
