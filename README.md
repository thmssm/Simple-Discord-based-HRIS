# Simple Discord HRIS

Attendance management system — Discord bot + web dashboard. Built for small teams that already use Discord.

## What it does

Track who shows up, who's late, who's absent — all through Discord. A bot watches voice channels for attendance, a dashboard shows everything in one place.

**No new app to install. No separate login (unless you want one). Your team already has Discord open.**

## Who is this for

| Use case | Why it fits |
|----------|------------|
| **Indie game studios** | Artists, devs, producers already hanging in Discord voice. Attendance tracks itself. |
| **Small production houses** | Shift-based, remote-friendly. Bot knows who joined when. |
| **Software dev teams** | Stand-ups, sprints, retrospectives — schedule recurring meetings with one command. |
| **Remote-first companies** | Under 100 employees. Discord is your office — now it's your HR system too. |
| **Startups & agencies** | Free to run. Zero infrastructure beyond a $5 VPS. |

## Features

### Discord Bot

- **Voice-based attendance** — joins a voice channel, marks you present. Leaves, marks you absent. Late after 10 AM? Flagged.
- **Natural language meetings** — type `@bot buat meeting Sprint besok jam 2 siang` and it schedules. Indonesian and English.
- **Recurring schedules** — set daily stand-ups, weekly reviews. Auto-generates meeting instances.
- **Absence tracking** — post in any designated text channel, bot parses your absence reason with AI. Supports sick leave, day off, paid leave.
- **Name & nickname matching** — mention colleagues by name or nickname. No @mention ping needed during off-hours.
- **Multi-channel commands** — responds in whitelisted channels only. Ignores DMs. No spam, no privacy issues.

### Web Dashboard

- **Today overview** — who's in voice right now, upcoming meetings, today's absences (dark theme, mobile-friendly)
- **Attendance per day** — Present / Late / Missing / Holiday / Weekend breakdown with per-member drilldown
- **Calendar** — monthly view with meeting dots, holiday markers, recurring schedule preview, click-for-details popup
- **Schedules** — CRUD recurring meetings, assign members, multi-day support (e.g. Mon-Fri stand-up)
- **Absence log** — all records with original Discord messages, date navigation, pagination
- **History** — concluded meetings with attendee analysis, overlap detection, [Recurring] and [One-time] tags
- **Member admin** — add/edit members with nickname field for easy bot commands
- **Login & security** — Cloudflare Turnstile, rate limiting, session-based auth, all write endpoints protected

## How it works

```
Discord voice join/leave  →  Bot tracks sessions  →  SQLite DB
Discord text commands     →  Bot parses with LLM   →  SQLite DB
Web dashboard             →  API reads DB          →  Display
```

- **Bot**: Python `discord.py` client. Runs 24/7 on a VPS. Connects to your Discord server.
- **LLM**: Uses any OpenAI-compatible API (DeepSeek by default). Swap to GPT-4, Claude, or local model — just change the endpoint and model name in a few lines.
- **API**: Python `http.server` on port 8081. All pages served inline (no build step, no Node.js).
- **DB**: SQLite with WAL mode. Handles concurrent reads from dashboard + writes from bot.
- **Frontend**: Static HTML/CSS/JS. Dark theme. Works on mobile.

## LLM Token Usage & Cost Estimation

The bot makes two types of LLM calls. Both use DeepSeek by default (swap to any OpenAI-compatible API).

### Per-call breakdown

| Call | Trigger | Input tokens | Output tokens | Total |
|------|---------|-------------|---------------|-------|
| **Command parsing** | Every `@bot` command | ~600 | ~60 | ~660 |
| **Absence parsing** | Every message in absence channel | ~400 | ~30 | ~430 |

### Real-world example: 50-employee company

**Monthly command usage** (typical):
- 20 meeting creations × 660 tokens = 13,200
- 50 meeting edits/cancels × 660 tokens = 33,000
- 30 meeting list queries × 660 tokens = 19,800
- 20 absence queries × 660 tokens = 13,200

**Monthly absence parsing**:
- 15 absence posts per day × 22 working days × 430 tokens = 141,900

**Total**: ~221,100 tokens/month

### Cost (DeepSeek pricing, as of 2024)

| | Input ($0.14/1M) | Output ($0.28/1M) |
|---|---|---|
| Commands (79,200 tokens) | $0.011 | $0.022 |
| Absences (141,900 tokens) | $0.020 | $0.040 |
| **Monthly total** | **~$0.09** | |

### Cost (OpenAI GPT-4o-mini)

| | Input ($0.15/1M) | Output ($0.60/1M) |
|---|---|---|
| **Monthly total** | | **~$0.20** |

**Bottom line**: For a 50-person team, LLM costs are under $0.25/month. The bot token and VPS are the only real costs.


## Setup

### Requirements

- Python 3.11+
- A Discord bot with `message_content`, `members`, `voice_states` intents enabled
- An LLM API key (DeepSeek, OpenAI, or any compatible provider)
- A VPS or any always-on machine ($5/month VPS is plenty)
- Cloudflare Turnstile (free, for login protection)

### Environment Variables

Create a `.env` file:

```
DISCORD_BOT_TOKEN=your_discord_bot_token
DEEPSEEK_API_KEY=your_deepseek_api_key
TURNSTILE_SECRET_KEY=your_turnstile_secret
```

To use a different LLM provider, change the API key variable and update the endpoint URL in `bot.py`.

### Quick Start

```bash
git clone https://github.com/thmssm/simple-discord-hris.git
cd simple-discord-hris
python3 -m venv .venv && source .venv/bin/activate
pip install discord.py

# Create DB
python3 -c "import sqlite3; db=sqlite3.connect('hr.db'); db.execute('PRAGMA journal_mode=WAL')"

# Start
python3 bot.py &
python3 dashboard_api.py &
```

### Production Setup

```ini
# /etc/systemd/system/hr-bot.service
[Unit]
Description=Discord HR Bot
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

```nginx
server {
    server_name dashboard.yourdomain.com;
    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header Cache-Control "no-store";
    }
}
```

### First Admin Account

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
| `meeting_schedules` | Recurring schedule templates (multi-day support) |
| `schedule_members` | Member assignment to schedules |
| `meeting_invites` | Per-meeting invite list |
| `voice_sessions` | Discord voice join/leave events |
| `absences` | Parsed absence records from text channel |
| `message_log` | Raw messages in absence channel (for audit) |
| `holidays` | Company holiday calendar |
| `credentials` | Hashed admin credentials (SHA256 + salt) |
| `sessions` | Active login sessions |
| `login_attempts` | Rate limiting audit log |

## Security

- All write endpoints require valid session cookie
- Login protected by Cloudflare Turnstile + IP rate limiting (5/min)
- Passwords hashed with SHA256 + random salt
- Sessions expire after 24 hours, HttpOnly cookies
- Bot token and API keys never stored in code — environment variables only
- Bot ignores DMs and non-whitelisted channels

## Design Decisions

- **SQLite over Postgres**: Zero setup, zero maintenance. WAL mode handles concurrent reads/writes. Fine for teams under 100.
- **Inline HTML/CSS**: No build step, no framework. Edit in any text editor. One file per page.
- **Natural language over slash commands**: Users type like they talk. LLM figures out the intent. No `/create_meeting --time 14:00` memorization.
- **Bot replies in-channel**: Transparent. Everyone sees the meeting being created. No secret DM threads.

## Roadmap

- **Weekly / monthly HR reports** — auto-generated attendance summary
- **Export to spreadsheet** — download attendance data as CSV or Excel
- **Leave balance tracking** — annual leave, sick leave quotas per employee


## License

Private. Contact for licensing.
