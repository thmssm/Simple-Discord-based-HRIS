# AGENTS.md — Agent Setup Guide

## What this is

Simple Discord HRIS — a Discord bot + web dashboard for attendance tracking. You are helping someone set this up. Follow these steps in order. Do NOT skip verification steps.

## Step 1: Prerequisites check

Ask the user for:
1. **Discord bot token** — from https://discord.com/developers/applications (needs: `message_content`, `members`, `voice_states` intents)
2. **LLM API key** — DeepSeek, OpenAI, or any OpenAI-compatible provider
3. **VPS or server** — any Ubuntu 22.04+ machine with public IP and domain pointed to it
4. **Cloudflare Turnstile keys** — free from Cloudflare dashboard (site key + secret key). Skip if login protection not needed.

## Step 2: Clone and configure

```bash
git clone https://github.com/thmssm/simple-discord-hris.git
cd simple-discord-hris
python3 -m venv .venv && source .venv/bin/activate
pip install discord.py
```

## Step 3: Configure bot.py

Open `bot.py` and find the configuration block near the top (~line 20). Change these:

```python
# REQUIRED: Set your Discord channel IDs
ABSENSI_CHANNEL_ID = 123456789012345678  # Channel where users post absences
CMD_CHANNEL_IDS = {123456789012345678}    # Channel(s) where @bot commands are allowed
```

## Step 4: (Optional) Change LLM provider

The bot uses DeepSeek by default. To use another provider, edit `parse_absence()` and `parse_command()` functions in `bot.py`. Change the model name and API endpoint:

```python
# In both parse_absence() and parse_command():
data = json.dumps({
    "model": "gpt-4o-mini",        # Change model
    ...
})
req = urllib.request.Request(
    "https://api.openai.com/v1/chat/completions",  # Change endpoint
    ...
)
```

## Step 5: Create .env file

```bash
cat > .env << 'EOF'
DISCORD_BOT_TOKEN=your_discord_bot_token
DEEPSEEK_API_KEY=your_deepseek_api_key
TURNSTILE_SECRET_KEY=your_turnstile_secret
EOF
```

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

Add to your `.env`:
```
TURNSTILE_SECRET_KEY=your_turnstile_secret_key
```

Also update the Turnstile **site key** in `login.html`:
```html
<div class="cf-turnstile" data-sitekey="0x4AAAAAA...your_site_key"></div>
```
The site key is public (embedded in the page) — the secret goes in `.env`.

## Step 9: Add team members

Members need to exist in the `members` table for the bot to track them:

```bash
python3 -c "
import sqlite3
db = sqlite3.connect('hr.db')
# Add a member
db.execute('INSERT INTO members (discord_id, discord_name, first_name, active) VALUES (?,?,?,1)',
    ('123456789012345678', 'user#1234', 'John'))
db.commit()
print('Member added')
"
```

Or add members through the web dashboard admin panel after login.

## Step 10: Deploy

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

### Nginx (optional — for domain-based access)

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

## Step 11: Verify

Check all of these before telling the user it's done:

1. `sudo systemctl status hr-bot hr-dashboard` — both `active`
2. `curl -s http://localhost:8081/` — returns 302 redirect to login
3. Bot appears online in Discord
4. Send a message in your absensi channel (e.g. "izin sakit") — bot logs it silently
5. Send `@bot meetings today` in the command channel — bot replies
6. Dashboard loads at `https://dashboard.yourdomain.com`
7. Login works with the admin credentials created in Step 7

## Pitfalls

- **Indentation errors**: After editing `.py` files, verify with `python3 -c "compile(open('bot.py').read(),'bot.py','exec')"` before restarting
- **SQLite locking**: The DB uses WAL mode. Both processes (bot + dashboard) write concurrently. Do NOT use SQLite CLI while services are running without `.timeout 5000`
- **Cloudflare proxy**: If using Cloudflare, enable "Development Mode" during setup to avoid challenge loops
- **Voice tracking**: Requires `voice_states` intent enabled in Discord Developer Portal, plus `PyNaCl` (`pip install PyNaCl`)
- **Bot not responding**: Check `CMD_CHANNEL_IDS` — bot only responds in whitelisted channels. Check `message_content` intent is enabled.
- **False absence reports**: If someone asks "sakit apa?" in your absensi channel as a reply, the bot should ignore it. If it doesn't, the reply context isn't being detected — check that the bot has `message_content` intent enabled and message cache is working.
