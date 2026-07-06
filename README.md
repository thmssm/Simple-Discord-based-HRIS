# Simple Discord-based HRIS

Attendance management system — Discord bot + web dashboard. Built for small teams that already use Discord.

> 🇮🇩 **Language note**: This system was originally built for an Indonesian game studio. It understands Indonesian phrases naturally (e.g. `"izin sakit"` = sick leave, `"cuti"` = day off, `"absensi"` = attendance/absence). It also handles English flawlessly — the LLM parser works in both languages. Which language works best depends on your LLM provider; DeepSeek and GPT handle Indonesian well, while local models may be more reliable in English.

## What it does

Track who shows up, who's late, who's absent — all through Discord. A bot watches voice channels for attendance, a dashboard shows everything in one place.

The bot also understands **conversations** in your absence channel — it can tell the difference between someone reporting sick (✅ captured, e.g. `"izin sakit"` = *"sick leave permission"*) and someone replying `"sakit apa?"` = *"what sickness?"* (✅ ignored). No more false positives from casual chat.

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

- **Voice-based attendance** — joins a voice channel, marks you present. Leaves, marks you absent. Late after the configured threshold (default 10:15 AM)? Flagged.
- **Natural language meetings** — type `@bot buat meeting Sprint besok jam 2 siang` (Indonesian: *"create a Sprint meeting tomorrow at 2 PM"*) and it schedules. Supports both Indonesian and English.
- **Recurring schedules** — set daily stand-ups, weekly reviews. Auto-generates meeting instances.
- **Absence tracking** — post in any designated text channel, bot parses your absence reason with AI. Supports sick leave, day off, paid leave.
- **Name & nickname matching** — mention colleagues by name or nickname. No @mention ping needed during off-hours.
- **Multi-channel commands** — responds in whitelisted channels only. Ignores DMs. No spam, no privacy issues.

### Web Dashboard

- **Today overview** — who's in voice right now, upcoming meetings, today's absences (dark theme, mobile-friendly)
- **Attendance per day** — Present / Late / Missing / Holiday / Weekend breakdown with per-member drilldown
- **People directory** — employee list with search, role, and division info
- **Person detail** — individual attendance profile with voice sessions, absences, and date-range summaries
- **Calendar** — monthly view with meeting dots, holiday markers, recurring schedule preview, click-for-details popup
- **Schedules** — CRUD recurring meetings, assign members, multi-day support (e.g. Mon-Fri stand-up)
- **Absence log** — all records with original Discord messages, date navigation, pagination
- **History** — concluded meetings with attendee analysis, overlap detection, [Recurring] and [One-time] tags
- **Reports** — attendance summaries, voice session breakdown, absence type distribution
- **Member admin** — add/edit members with nickname field for easy bot commands
- **Login & security** — Cloudflare Turnstile, rate limiting, session-based auth, all write endpoints protected
- **Responsive M3 nav** — navigation rail on desktop, collapsible icons on tablet, drawer on mobile
- **Static HTML demo** — standalone demo at `/demo/` with hardcoded data, no backend needed

## Discord Server Setup

The bot works best with dedicated channels. Here's a recommended structure you can create inside any Discord server:

### Recommended Category & Channels

```
📋 HRIS
├── 📢 announcements        # Bot delivers daily summaries, alerts
├── 🗣️ general-voice        # Voice channel for daily attendance tracking
├── 📝 absensi              # Absence channel — bot reads every message here
└── 🤖 hr-bot-commands      # Bot command channel — @bot commands only work here
```

| Channel | Purpose | Configuration |
|---------|---------|---------------|
| **Absence channel** (`absensi`) | Members post their absences here. Bot reads every message, parses intent via LLM, and records sick leave, day off, paid leave, etc. Replies and casual chat are automatically filtered out. | Set `ABSENSI_CHANNEL_ID` in `.env` to this channel's ID |
| **Command channel** (`hr-bot-commands`) | `@bot` commands like meeting creation, scheduling, and queries work here. Commands outside this channel (and DMs) are silently ignored. | Set `CMD_CHANNEL_IDS` in `.env` (comma-separated IDs) or edit `bot.py` line 22 |
| **Voice channels** (`general-voice`) | Bot auto-tracks join/leave events — marks members present while in voice, late if they join after the threshold. No configuration needed, just create the channel. | Auto-detected — no config required |
| **Announcements** (`announcements`) | Bot delivers automated summaries (morning check-in, evening recap) and watchdog alerts here. | Configure via your cron or scheduling system |

### Finding Channel IDs

Enable **Developer Mode** in Discord: Settings → Advanced → Developer Mode. Then right-click any channel → **Copy ID**.

```bash
# Example .env config:
ABSENSI_CHANNEL_ID=123456789012345678
CMD_CHANNEL_IDS=987654321098765432,123456789098765432
```

### Bot Permissions & Intents

When creating the bot application at the [Discord Developer Portal](https://discord.com/developers/applications), enable these **Privileged Gateway Intents**:

| Intent | Why it's needed |
|--------|----------------|
| **Message Content** | Read messages in the absence and command channels |
| **Server Members** | Resolve member names and nicknames |
| **Voice States** | Track when members join/leave voice channels |

Recommended bot permissions (invite with this integer: `277562703936`):

- Read Messages / View Channels
- Send Messages
- Read Message History
- Connect (voice)
- Speak (voice — optional)

### Security Best Practices

- **Restrict command channels** — only whitelist channels the HR team monitors. Bot ignores everything else, preventing accidental triggers from casual chat.
- **Separate absence channel** — keeping absences in one channel makes auditing easy and prevents the LLM parser from seeing unrelated conversations.
- **No DM access** — the bot hard-skips DMs (`if not message.guild: return`). Members can't DM the bot commands or absence reports.
- **Private command channels** — make the `hr-bot-commands` channel visible only to HR/admins if you want sensitive operations restricted.
- **Logging** — the bot writes logs to `bot.log` (configurable via `HRBOT_LOG_PATH`). Monitor it for parsing errors or unexpected behavior.

### Channel Configuration Summary

All channel IDs go into `.env`:

```ini
# Channel where absence messages are monitored
ABSENSI_CHANNEL_ID=123456789012345678

# Comma-separated channel IDs where @bot commands are allowed
CMD_CHANNEL_IDS=987654321098765432,123456789098765432
```

> Without these configured, the bot will connect but won't process any messages. Voice tracking still works — attendance from voice channels requires no channel config.

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
- **Frontend**: Static HTML/CSS/JS. Dark theme. Mobile-friendly. M3-inspired navigation rail with drawer.

## LLM Token Usage & Cost Estimation

The bot makes two types of LLM calls. Current default: **DeepSeek V4 Flash**. Swap to any OpenAI-compatible API.

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

**Total**: ~221,100 tokens/month (~190,000 input, ~31,000 output)

### Estimated cost (DeepSeek V4 Flash, June 2026)

| | Cache hit ($0.0028/1M) | Cache miss ($0.14/1M) | Output ($0.28/1M) |
|---|---|---|---|
| Commands (66,000 in, 6,000 out) | $0.0002 | $0.009 | $0.002 |
| Absences (120,000 in, 6,000 out) | $0.0003 | $0.017 | $0.002 |
| **Monthly total (mostly cache miss)** | | **~$0.03** | |
| **Monthly total (mostly cache hit)** | | **~$0.005** | |

> ⚠️ **Disclaimer**: Token counts are estimates. Actual usage depends on message length and LLM behavior. Pricing varies by provider and changes over time. Always verify with your provider before deploying.


## Hosting Options

### Option 1: VPS (recommended)

A cheap VPS runs both the bot and dashboard. No GPU needed — LLM calls go to the API.

| Team size | Spec | Provider | Monthly cost |
|-----------|------|----------|-------------|
| 1–25 users | 1 vCPU, 1 GB RAM, 25 GB SSD | Hetzner CX22, DigitalOcean, Linode | ~$5 |
| 25–50 users | 2 vCPU, 2 GB RAM, 40 GB SSD | Hetzner CX32 | ~$10 |
| 50–100 users | 2 vCPU, 4 GB RAM, 60 GB SSD | Hetzner CX42 | ~$20 |

**What scales**: The bot uses async I/O — one small VPS handles 100+ Discord users easily. The bottleneck is LLM API latency, not CPU.

**Setup time**: ~30 minutes. Ubuntu 22.04, Python 3.11, systemd, nginx, Cloudflare.

### Option 2: Self-hosted (zero cost)

Run everything on a spare machine or home server. Connect to a local LLM via Ollama.

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b

# Update bot.py:
# model = "qwen2.5:7b"
# api_url = "http://localhost:11434/v1/chat/completions"
```

**Requirements**: 8+ GB RAM for 7B quantized model. No GPU needed. Zero API costs.

**Trade-off**: Local models may be less accurate for non-English languages (e.g. Indonesian). Fine for basic commands, but absence parsing may need tuning.
**Bottom line**: LLM costs are negligible. A $5 VPS is the only real expense. Discord bot tokens are free.


> 🤖 **AI Agent?** Read [AGENTS.md](AGENTS.md) for step-by-step setup instructions designed for automated deployment.


## Setup

### Requirements

- Python 3.11+
- A Discord bot with `message_content`, `members`, `voice_states` intents enabled
- An LLM API key (DeepSeek, OpenAI, or any compatible provider)
- A VPS or any always-on machine ($5/month VPS is plenty)
- Cloudflare Turnstile (free, for login protection)

### Environment Variables

Create a `.env` file (see `.env.example` for all options):

```
DISCORD_BOT_TOKEN=your_d...oken
DEEPSEEK_API_KEY=your_d..._key
TURNSTILE_SECRET_KEY=your_t...cret
```

Optional vars: `HRBOT_DB_PATH`, `HRBOT_LOG_PATH`, `HRBOT_SERVICE`, `ABSENSI_CHANNEL_ID`.

To use a different LLM provider, change the API key variable and update the endpoint URL in `bot.py`.

### Quick Start

```bash
git clone https://github.com/thmssm/Simple-Discord-based-HRIS.git
cd Simple-Discord-based-HRIS
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
WorkingDirectory=/opt/hr-bot
EnvironmentFile=/opt/hr-bot/.env
ExecStart=/opt/hr-bot/.venv/bin/python3 bot.py
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

## Tuning the LLM Absence Parser

The bot uses an LLM to parse messages in your absence channel — it figures out who's reporting sick, taking leave, or just chatting. **The default prompt is trained on an Indonesian studio's communication style.** Your team will talk differently.

### Why tune it

Without tuning, you may get:
- **False positives**: casual chat or replies to others mistakenly recorded as absences
- **False negatives**: someone saying `"can't work today, migraines"` not being captured

### Tuning process

1. **Let it run for 3–5 working days** to collect real messages from your team
2. **Audit the logs** — query the `message_log` table:
   ```sql
   SELECT user_name, content, llm_intent, llm_absence_type FROM message_log ORDER BY id DESC;
   ```
3. **Find false positives** — messages marked `report_absence` that should be `ignore` (e.g. `"is John okay?"`)
4. **Find false negatives** — messages marked `ignore` that should be `report_absence` (e.g. `"sick today, can't come in"`)
5. **Update the prompt** — open `bot.py`, find `parse_absence()`, and add your team's real examples to both the "SELF-REPORT" and "COMMENTARY/REPLY/INFO" sections
6. **Test with the CLI** — `python3 parse_absence.py "your test message"`
7. **Restart the bot** — `sudo systemctl restart hr-bot`

> 💡 See [AGENTS.md](AGENTS.md) for detailed guidance on this process, including the SQL queries and CLI tool usage.

## Demo

A standalone static HTML demo is available at **[/demo/](https://thmssm.github.io/Simple-Discord-based-HRIS/demo/)**. All data is hardcoded — no backend, no database, no setup required.

## Roadmap

- **Weekly / monthly HR reports** — auto-generated attendance summary
- **Export to spreadsheet** — download attendance data as CSV or Excel
- **Leave balance tracking** — annual leave, sick leave quotas per employee


## License

MIT. Use freely.
