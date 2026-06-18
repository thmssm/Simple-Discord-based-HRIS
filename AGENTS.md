# AGENTS.md — Agent Setup Guide

## What this is

Simple Discord HRIS — a Discord bot + web dashboard for attendance tracking. You are helping someone set this up. Follow these steps in order. Do NOT skip verification steps.

> 🇮🇩 **Language note**: This project uses some Indonesian terms in its code and configuration:
> - `absensi` = attendance / absence check-in
> - `izin sakit` = sick leave permission
> - `cuti` = day off / leave
> - `besok` / `hari ini` / `kemarin` = tomorrow / today / yesterday
> 
> These are meaningful to the bot's LLM parser — users can type in either Indonesian or English and it will understand both.

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

## Step 11: (Optional) Set up the Windows Monitor

The repo includes `monitor-hr-bot.bat` — a local Windows tool for real-time bot monitoring:

1. Open `monitor-hr-bot.bat` in a text editor
2. Edit the configuration at the top:

```batch
set VPS_HOST=ubuntu@your-server-ip
set VPS_BOT_DIR=.
set DASHBOARD_URL=https://dashboard.yourdomain.com
```

3. Save the file (keep CRLF line endings)
4. Double-click `monitor-hr-bot.bat` to run

**Requirements:** Windows 10+, OpenSSH Client (install via Settings > Apps > Optional Features), curl.

**Modes:**
- **Dashboard View [1]** — creates an SSH tunnel to the API, polls every 10s, shows colored dashboard
- **Bot Log Tail [2]** — SSH tail of bot.log in real-time
- **Journal Tail [3]** — systemd journal for service-level logs
- **SQL Query [4]** — quick-select or custom SQL against the live DB
- **Health Monitor [5]** — polls `/api/health` every 30s, green/red status

## Step 12: Verify

Check all of these before telling the user it's done:

1. `sudo systemctl status hr-bot hr-dashboard` — both `active`
2. `curl -s http://localhost:8081/` — returns 302 redirect to login
3. Bot appears online in Discord
4. Send a message in your absensi channel (e.g. `"izin sakit"` = sick leave, `"pagi, hari ini izin cuti"` = *"morning, today I'm taking leave"*) — bot logs it silently without responding
5. Send `@bot meetings today` in the command channel — bot replies
6. Dashboard loads at `https://dashboard.yourdomain.com`
7. Login works with the admin credentials created in Step 7

## Post-Setup: Tune the LLM prompt to your team's culture

The absence parser is powered by an LLM prompt in `bot.py` → `parse_absence()`. By default, it includes example phrases from an Indonesian studio. **Your team will say things differently.** After running for a few working days, you'll want to tune this prompt.

### Why this matters

The LLM is good at understanding natural language, but it needs to know **what your team considers an "absence" versus "just chatting"**. In the original studio, messages like:

- `"Pagi, mati lampu di sini"` (= *"Morning, power is out here"*) → should be `ignore` (just informing, not taking leave)
- `"Coba lapor lewat aplikasi PLN"` (= *"Try reporting via the PLN app"*) → should be `ignore` (reply/advice to someone else)
- `"sakit apa? kecelakaan kenapa?"` (= *"what sickness? what accident?"*) → should be `ignore` (asking about someone else)

Your team's culture around absence reporting may differ. Some teams are very formal (`"I request permission for sick leave"`), others are casual (`"can't make it today"`). The prompt needs to reflect that.

### Tuning process

1. **Let it run for 3–5 working days.** Collect real messages from your team in the message_log table.
2. **Check the logs** — query messages the LLM parsed:

```sql
SELECT user_name, content, llm_intent, llm_absence_type, parsed_note
FROM message_log ORDER BY id DESC;
```

3. **Find false positives** — messages marked `report_absence` that should have been `ignore` (e.g. someone asking about a colleague's health, or general chat).
4. **Find false negatives** — messages marked `ignore` that should have been `report_absence` (e.g. someone saying `"can't work today, migraines"` that the bot didn't catch).
5. **Add your team's real examples** to the prompt in `parse_absence()` — both examples of what IS an absence and what IS NOT. The more examples you add from actual team messages, the better the LLM gets.
6. **Test with the CLI tool** — `python3 parse_absence.py "your test message here"` — to verify the prompt handles new phrases before deploying.
7. **After tuning, restart the bot** — `sudo systemctl restart hr-bot`

> 💡 **Tip**: Keep updating the prompt as your team develops new habits. A prompt that was tuned after week 1 will be significantly more accurate than the default.

## Pitfalls
- **Indentation errors**: After editing `.py` files, verify with `python3 -c "compile(open('bot.py').read(),'bot.py','exec')"` before restarting
- **SQLite locking**: The DB uses WAL mode. Both processes (bot + dashboard) write concurrently. Do NOT use SQLite CLI while services are running without `.timeout 5000`
- **Cloudflare proxy**: If using Cloudflare, enable "Development Mode" during setup to avoid challenge loops
- **Voice tracking**: Requires `voice_states` intent enabled in Discord Developer Portal, plus `PyNaCl` (`pip install PyNaCl`)
- **Bot not responding**: Check `CMD_CHANNEL_IDS` — bot only responds in whitelisted channels. Check `message_content` intent is enabled.
- **False absence reports**: If someone asks `"sakit apa?"` (= *"what sickness?"*) in your absensi channel as a reply, the bot should ignore it. If it doesn't, the reply context isn't being detected — check that the bot has `message_content` intent enabled and message cache is working.
