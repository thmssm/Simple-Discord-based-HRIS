# AGENTS.md — Agent Setup Guide

## What this is

Simple Discord HRIS — a Discord bot + web dashboard for attendance tracking. You are helping someone set this up. Follow these steps in order. Do NOT skip verification steps.

## Step 1: Prerequisites check

Ask the user for:
1. **Discord bot token** — from https://discord.com/developers/applications (needs: message_content, members, voice_states intents)
2. **DeepSeek API key** — from https://platform.deepseek.com (or any OpenAI-compatible key)
3. **VPS or server** — any Ubuntu 22.04+ machine with public IP and domain pointed to it
4. **Cloudflare Turnstile keys** — free from Cloudflare dashboard (site key + secret key). Skip if login protection not needed.

## Step 2: Clone and configure

```bash
git clone https://github.com/thmssm/simple-discord-hris.git
cd simple-discord-hris
python3 -m venv .venv && source .venv/bin/activate
pip install discord.py
```

## Step 3: Edit bot config

Open `bot.py` and find the configuration block near the top. Change these:

```python
# Line ~18-22 — REQUIRED CHANGES
CMD_CHANNEL_IDS = {REPLACE_WITH_YOUR_CHANNEL_ID}  # Whitelisted command channels
ABSENCE_CHANNEL_ID = REPLACE_WITH_YOUR_CHANNEL_ID  # Channel for absence messages

# Line ~90 — Timezone offset from UTC (7 = GMT+7, 8 = GMT+8, etc.)
TZ_OFFSET = 7  # Change to your timezone

# Line ~85 — Meeting late threshold (military time in your timezone)
LATE_HOUR = 10  # 10 AM local time
```

## Step 4: Configure LLM provider

In `bot.py`, lines ~225-245, change the API endpoint and model:

```python
# Default: DeepSeek
api_url = "https://api.deepseek.com/v1/chat/completions"
model = "deepseek-chat"

# For OpenAI:
# api_url = "https://api.openai.com/v1/chat/completions"
# model = "gpt-4o-mini"

# For Ollama (local):
# api_url = "http://localhost:11434/v1/chat/completions"
# model = "qwen2.5:7b"
```

## Step 5: Create .env file

```bash
cat > .env << 'EOF'
DISCORD_BOT_TOKEN=the...
Add additional environment variables as needed.

## Step 6: Initialize the database

```bash
python3 -c "
import sqlite3
db = sqlite3.connect('hr.db')
db.execute('PRAGMA journal_mode=WAL')
# All tables are auto-created on first bot run
db.close()
"
```

## Step 7: Create admin account

```bash
python3 -c "
import sqlite3, hashlib, secrets
db = sqlite3.connect('hr.db')
db.execute('''CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')
s = secrets.token_hex(16)
pw = input('Enter admin password: ')
h = hashlib.sha256(f'{s}:{pw}'.encode()).hexdigest()
db.execute('INSERT INTO credentials (username, password_hash) VALUES (?,?)', ('admin', f'{s}:{h}'))
db.commit()
print('Admin account created')
db.close()
"
```

## Step 8: Configure Turnstile (login protection)

If using login protection, open `dashboard_api.py` and set the Turnstile keys:

```python
# Environment variable (set in .env):
TURNSTILE_SECRET_KEY=your...

### Deploy

```bash
# Create systemd service for bot
sudo tee /etc/systemd/system/hr-bot.service << 'EOF'
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
EOF

# Create systemd service for dashboard
sudo tee /etc/systemd/system/hr-dashboard.service << 'EOF'
[Unit]
Description=HR Dashboard API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=.
EnvironmentFile=./.env
ExecStart=./.venv/bin/python3 dashboard_api.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now hr-bot hr-dashboard
```

### Nginx

```bash
sudo apt-get install -y nginx
sudo tee /etc/nginx/sites-available/hr-dashboard << 'EOF'
server {
    server_name dashboard.yourdomain.com;
    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header Cache-Control "no-store";
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/hr-dashboard /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d dashboard.yourdomain.com
```

## Step 9: Verify

Check all of these before telling the user it's done:

1. `sudo systemctl status hr-bot hr-dashboard` — both active
2. `curl -s http://localhost:8081/` — returns 302 redirect
3. Bot appears online in Discord
4. Send `@bot help` in the whitelisted channel — bot replies
5. Dashboard loads at `https://dashboard.yourdomain.com`
6. Login works with the admin credentials created in Step 7

## Pitfalls

- **Indentation errors**: If you edit `bot.py` or `dashboard_api.py`, verify with `python3 -c "compile(open('bot.py').read(),'bot.py','exec')"` before restarting
- **SQLite locking**: The DB uses WAL mode. Both processes (bot + dashboard) write concurrently. Do NOT use SQLite CLI while services are running without `.timeout 5000`
- **Cloudflare proxy**: If using Cloudflare, enable "Development Mode" during setup to avoid challenge loops
- **Voice tracking**: Requires `voice_states` intent enabled in Discord Developer Portal AND PyNaCl installed (`pip install PyNaCl`)
- **Bot not responding**: Check `CMD_CHANNEL_IDS` — bot only responds in whitelisted channels. Check `message_content` intent is enabled.
