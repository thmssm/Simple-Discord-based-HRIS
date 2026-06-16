#!/usr/bin/env python3
"""YourOrg HR Bot — Discord attendance, absence, and voice tracker."""

import os
import sqlite3
import json
import logging
import re
from datetime import datetime, date, timedelta
from pathlib import Path

import discord

# ── Config ──────────────────────────────────────────────
TOKEN = os.environ["HRBOT_TOKEN"]
DEEPSEEK_KEY = os.environ["DEEPSEEK_API_KEY"]
DB_PATH = Path("./hr.db")
LOG_PATH = Path("./bot.log")
ABSENSI_CHANNEL_ID = 1037917883285655654
CMD_CHANNEL_IDS = {1516027352797151302, 1516408275871076352}  # @bot commands only here

# ── Logging ─────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hrbot")

# ── Database ────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(DB_PATH); db.execute("PRAGMA busy_timeout=5000")
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS divisions (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY,
            discord_id TEXT UNIQUE,
            discord_name TEXT,
            first_name TEXT,
            last_name TEXT,
            gender TEXT,
            role TEXT,
            division_id INTEGER,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS absences (
            id INTEGER PRIMARY KEY,
            user_id TEXT,
            user_name TEXT,
            absence_type TEXT,
            date TEXT,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS meeting_schedules (
            id INTEGER PRIMARY KEY,
            name TEXT,
            day_of_week INTEGER,
            start_time TEXT,
            end_time TEXT,
            channel_id TEXT,
            channel_name TEXT
        );
        CREATE TABLE IF NOT EXISTS schedule_members (
            schedule_id INTEGER,
            discord_id TEXT,
            PRIMARY KEY (schedule_id, discord_id)
        );
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY,
            name TEXT,
            date TEXT,
            start_time TEXT,
            end_time TEXT,
            channel_id TEXT,
            channel_name TEXT,
            created_by TEXT,
            created_by_name TEXT,
            cancelled INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS meeting_invites (
            id INTEGER PRIMARY KEY,
            meeting_id INTEGER,
            user_id TEXT,
            user_name TEXT,
            attended INTEGER DEFAULT 0,
            join_time TEXT,
            leave_time TEXT
        );
        CREATE TABLE IF NOT EXISTS voice_sessions (
            id INTEGER PRIMARY KEY,
            user_id TEXT,
            user_name TEXT,
            channel_id TEXT,
            channel_name TEXT,
            join_time TEXT,
            leave_time TEXT,
            duration_minutes INTEGER,
            matched_meeting_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS message_log (
            id INTEGER PRIMARY KEY,
            user_id TEXT,
            user_name TEXT,
            content TEXT,
            llm_intent TEXT,
            llm_absence_type TEXT,
            parsed_date TEXT,
            parsed_note TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit()
    db.close()

# ── Helpers ─────────────────────────────────────────────
def is_whitelisted(user_id):
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM members WHERE discord_id=? AND active=1", (str(user_id),)
    ).fetchone()
    db.close()
    return row is not None

def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def today_str():
    return date.today().isoformat()

DAY_NAMES_ID = {
    "senin": 0, "selasa": 1, "rabu": 2, "kamis": 3,
    "jumat": 4, "sabtu": 5, "minggu": 6,
    "jumat": 4, "jum'at": 4,
}

def resolve_day(day_text, today):
    """Resolve Indonesian day name to YYYY-MM-DD."""
    day_text = day_text.lower().strip()
    if day_text in ("kemarin", "yesterday"):
        return (today - timedelta(days=1)).isoformat()
    if day_text in ("hari ini", "today", "hariini"):
        return today.isoformat()
    if day_text in ("besok", "tomorrow", "besuk"):
        return (today + timedelta(days=1)).isoformat()
    if day_text in DAY_NAMES_ID:
        target = DAY_NAMES_ID[day_text]
        current = today.weekday()
        days_ahead = (target - current) % 7
        if days_ahead == 0:
            days_ahead = 7  # next week, not today
        return (today + timedelta(days=days_ahead)).isoformat()
    return None

def resolve_mentions(text):
    """Extract Discord user IDs from <@ID> mentions in text. Returns list of IDs."""
    return re.findall(r"<@!?(\d+)>", text)

def local_to_utc(time_str):
    """Convert GMT+7 time (HH:MM) to UTC time string."""
    try:
        parts = time_str.strip().split(":")
        h = int(parts[0])
        m = int(parts[1])
        utc_h = (h - 7) % 24
        return f"{utc_h:02d}:{m:02d}:00"
    except:
        return time_str

# ── DeepSeek Parser ─────────────────────────────────────
def parse_command(text, user_name):
    import urllib.request

    today = date.today()
    day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    today_name = day_names[today.weekday()]

    prompt = f"""You are an Indonesian COMMAND PARSER for a Discord HR bot. Return ONLY JSON.

Today is {today.isoformat()} ({today_name}).

Valid intents:
- create_meeting: {{intent, meeting_name, day_text, start_time, end_time, channel, users[]}}
  Used when someone wants to CREATE a NEW meeting (one-time, not recurring).
  Examples:
    "buat meeting hari rabu, jam 11 pagi, 1 jam, perlu invite @Dirga @Thomas"
    "jadwalin rapat besok jam 2 siang, 30 menit di #UI/UX"
    "meeting sprint jam 09:00-10:00 di #Product: Metaverse @Andry @Clara"
    "bikinin meeting standup selasa jam 8 pagi, invite @Sigit"
    "buat meeting daily jam 3 sore, 1 jam, di #backend"

  RULES:
  - "kemarin" or "yesterday" → day_text: "kemarin"
  - "hari ini" or "today" → day_text: "hari ini"
  - "besok" or "tomorrow" → day_text: "besok"
  - "hari rabu" / "selasa" / etc → day_text: "rabu" / "selasa" / etc
  - "jam 11 pagi" → start_time: "11:00", "jam 2 siang" → "14:00", "jam 3 sore" → "15:00"
  - "1 jam" / "30 menit" / "2 jam" → calculate end_time from start
  - If explicit time range given ("jam 9-10" or "09:00-10:00") → use it directly
  - "@name" references in Discord appear as <@USER_ID> — extract the numeric ID
  - channel: look for #channel-name or "di #channel" or "di channel"
  - meeting_name: derive from context; use "Meeting" if unclear
  - users: array of {{id, name}} objects from @mentions

- edit_meeting: {{intent, meeting_id, meeting_name, changes: {{time, channel, cancel}}}}
  Examples: "ubah meeting 4 ke jam 10 malam", "pindah meeting Retrospective ke #UI/UX", "cancel meeting Sprint"
  Use meeting_name when user refers to meeting by name, meeting_id when by number.

- list_meetings: {{intent, period: "today"|"tomorrow"|"week"}}
  Examples: "meetings today", "meeting apa aja hari ini"

- absent_query: {{intent, period: "today"|"yesterday"|"week"|"month"}}

- ignore: {{intent, reason: "not a command"}}

User {user_name}: "{text}"

Return JSON ONLY:"""

    data = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0
    }).encode()

    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())

    content = result["choices"][0]["message"]["content"]
    # Clean markdown code fences
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\n", "", content)
        content = re.sub(r"\n```$", "", content)
    return json.loads(content)

# ── Absence Parser ──────────────────────────────────────
def parse_absence(text, user_name):
    """Parse free-text absence message via DeepSeek."""
    import urllib.request
    
    prompt = f"""You parse employee absence messages. Return ONLY JSON.

Extract: {{intent, absence_type, date, note}}
- intent: "report_absence" or "ignore"
- absence_type: "day_off", "sick", "afk", "paid_leave", or "other"
- date: YYYY-MM-DD (default: today)
- note: brief reason

User: {user_name}
Message: "{text}"

Return JSON:"""

    data = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 150, "temperature": 0
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=data,
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    content = result["choices"][0]["message"]["content"].strip()
    if content.startswith("```"): 
        content = re.sub(r"^```(?:json)?\n", "", content)
        content = re.sub(r"\n```$", "", content)
    return json.loads(content)

def get_real_name(user_id):
    """Get first_name + last_name from members table."""
    db = get_db()
    row = db.execute(
        "SELECT first_name, last_name FROM members WHERE discord_id=?",
        (str(user_id),)
    ).fetchone()
    db.close()
    if row and row[0]:
        return (row[0] + " " + (row[1] or "")).strip()
    return str(user_id)

# ── Bot ────────────────────────────────────────────────

def resolve_named_mentions(text):
    """Find member names in text and return their discord_ids."""
    db = get_db()
    members = db.execute("SELECT discord_id, first_name, last_name, nickname FROM members WHERE active=1").fetchall()
    db.close()
    found = []
    text_lower = text.lower()
    for m in members:
        full = (m["first_name"] + " " + (m["last_name"] or "")).strip().lower()
        first = m["first_name"].lower()
        nick = (m["nickname"] or "").lower()
        if nick and len(nick) > 2 and nick in text_lower:
            found.append(m["discord_id"])
        elif len(full) > 3 and full in text_lower:
            found.append(m["discord_id"])
        elif len(first) > 3 and first in text_lower:
            found.append(m["discord_id"])
    return found


def _safe_str(val, default=""):
    """Safely convert LLM output to string."""
    if val is None:
        return default
    if isinstance(val, dict):
        return default
    return str(val)

def _safe_time(val, default="09:00"):
    """Safely extract time from LLM output (string or dict)."""
    if val is None:
        return default
    if isinstance(val, dict):
        s = val.get("start") or val.get("time") or default
        return str(s) if s else default
    s = str(val)
    return s if ":" in s else f"{s}:00"

class HRBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        intents.voice_states = True
        super().__init__(intents=intents)

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        print(f"✅ {self.user} is online")
        
        # Build members map for name resolution
        db_init = get_db()
        members_map = {m["discord_id"]: (m["first_name"] + " " + (m["last_name"] or "")).strip()
                       for m in db_init.execute("SELECT discord_id, first_name, last_name FROM members", ()).fetchall()}
        db_init.close()
        
        # Auto-generate today's meetings from recurring schedules
        today = date.today()
        # Skip if today is a holiday
        import sqlite3 as _sq
        _db = _sq.connect(DB_PATH)
        _h = _db.execute("SELECT 1 FROM holidays WHERE date=?", (today.isoformat(),)).fetchone()
        _db.close()
        if _h:
            log.info("Today is a holiday — skipping meeting auto-generation")
        else:
            day_num = today.weekday()
            db = get_db()
            existing = [r["name"] for r in db.execute("SELECT name FROM meetings WHERE date=?", (today.isoformat(),)).fetchall()]
            scheds = db.execute("SELECT * FROM meeting_schedules WHERE ',' || day_of_week || ',' LIKE '%,' || ? || ',%'", (day_num,)).fetchall()
            for s in scheds:
                if s["name"] not in existing:
                    # Skip if meeting end time already passed
                    end_utc = local_to_utc(s["end_time"])
                    if f"{today.isoformat()} {end_utc}" < now_str():
                        continue
                    db.execute(
                        "INSERT INTO meetings (name, date, start_time, end_time, channel_id, channel_name) VALUES (?,?,time(?,?),time(?,?),?,?)",
                        (s["name"], today.isoformat(), s["start_time"], "-7 hours", s["end_time"], "-7 hours", s["channel_id"], s["channel_name"]),
                    )
                    meeting_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    # Auto-create meeting_invites for assigned schedule members
                    assigned = db.execute(
                        "SELECT discord_id FROM schedule_members WHERE schedule_id=?", (s["id"],)
                    ).fetchall()
                    for a in assigned:
                        real_name = members_map.get(a["discord_id"], a["discord_id"])
                        db.execute(
                            "INSERT INTO meeting_invites (meeting_id, user_id, user_name) VALUES (?,?,?)",
                            (meeting_id, a["discord_id"], real_name),
                        )
            db.commit()
        
            # Close all stale sessions from previous run
            db.execute("UPDATE voice_sessions SET leave_time=?, duration_minutes=CAST((julianday(?) - julianday(join_time)) * 1440 AS INTEGER) WHERE leave_time IS NULL", (now_str(), now_str()))
            db.commit()
        
            # Scan current voice state
            for guild in self.guilds:
                for ch in guild.voice_channels:
                    for member in ch.members:
                        if member.id == self.user.id: continue
                        db.execute(
                            "INSERT INTO voice_sessions (user_id, user_name, channel_id, channel_name, join_time) VALUES (?,?,?,?,?)",
                            (str(member.id), str(member)[:50], str(ch.id), ch.name[:50], now_str())
                        )
                        log.info(f"STARTUP VOICE: {member} in {ch.name}")
            db.commit()
            db.close()

        # Sync channels for schedule dropdown
        db2 = get_db()
        db2.execute("DELETE FROM channels")
        for guild in self.guilds:
            for ch in guild.voice_channels:
                db2.execute("INSERT OR IGNORE INTO channels (channel_id, channel_name) VALUES (?,?)", (str(ch.id), ch.name[:80]))
        db2.commit()
        db2.close()

    async def on_message(self, message):
        # Ignore self
        if message.author == self.user:
            return
        # Ignore DMs
        if not message.guild:
            return
        log.info("MSG [%s] (%s) %s: %s", message.channel.name, message.channel.id, message.author.name, message.content[:80])
        # ── Absensi channel: parse EVERY message ────────
        if message.channel.id == ABSENSI_CHANNEL_ID:
            user_id = str(message.author.id)
            if not is_whitelisted(user_id):
                return
            text = message.content.strip()
            if not text:
                return
            
            real_name = get_real_name(user_id)
            log.info(f"ABSENSI from {real_name}: {text[:100]}")
            try:
                parsed = parse_absence(text, real_name)
            except Exception as e:
                log.error(f"Absensi parse error: {e}")
                return
            
            db = get_db()
            db.execute(
                "INSERT INTO message_log (user_id, user_name, content, llm_intent, llm_absence_type, parsed_date, parsed_note, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (user_id, real_name, text[:1000], parsed.get("intent","unknown"),
                 parsed.get("absence_type",""), parsed.get("date",""), parsed.get("note","")[:200], now_str())
            )
            
            if parsed.get("intent") == "report_absence":
                date_str = parsed.get("date", today_str())
                existing = db.execute(
                    "SELECT id FROM absences WHERE user_id=? AND date=?",
                    (user_id, date_str)
                ).fetchone()
                if existing:
                    db.execute(
                        "UPDATE absences SET absence_type=?, note=?, created_at=? WHERE id=?",
                        (parsed.get("absence_type","other"), parsed.get("note","")[:200], now_str(), existing["id"]),
                    )
                else:
                    db.execute(
                        "INSERT INTO absences (user_id, user_name, absence_type, date, note, original_message) VALUES (?,?,?,?,?,?)",
                        (user_id, real_name, parsed.get("absence_type","other"), date_str, parsed.get("note","")[:200], text[:1000]),
                    )
            db.commit()
            db.close()
            return
        
        # ── Command channels: only @bot mentions in CMD channel ─────────
        if message.channel.id not in CMD_CHANNEL_IDS:
            return
        if self.user not in message.mentions:
            return

        user_id = str(message.author.id)
        if not is_whitelisted(user_id):
            return  # Silent ignore

        # Strip @bot mention from message
        text = re.sub(rf"<@!?{self.user.id}>", "", message.content).strip()
        if not text:
            await message.reply("Halo! Ketik perintah setelah @bot. Contoh: `@bot meetings today`")
            return

        log.info(f"CMD from {message.author.name}: {text}")

        try:
            parsed = parse_command(text, message.author.name)
        except Exception as e:
            log.error(f"LLM parse error: {e}")
            await message.reply("⚠️ Gagal memahami perintah. Coba lagi.")
            return

        intent = parsed.get("intent", "ignore")
        
        if intent == "create_meeting":
            await self.handle_create_meeting(message, parsed)
        elif intent == "edit_meeting":
            if not parsed.get("meeting_id") or not parsed.get("changes"):
                await message.reply("❓ Mau ubah meeting yang mana dan apa yang diubah? Contoh: `ubah meeting 2 ke jam 20-21` atau `pindah meeting 2 ke #UI/UX`. Ketik `meetings today` buat lihat daftar meeting hari ini.")
            else:
                await self.handle_edit_meeting(message, parsed)
        elif intent == "list_meetings":
            await self.handle_list_meetings(message, parsed)
        elif intent == "absent_query":
            await self.handle_absent_query(message, parsed)
        elif intent == "ignore":
            pass  # Silent
        else:
            await message.reply("❓ Perintah tidak dikenali. Coba: `@bot buat meeting ...`, `@bot meetings today`, `@bot absent today`")

    # ── Command Handlers ─────────────────────────────
    async def handle_create_meeting(self, message, parsed):
        """Create a one-time meeting with natural language parsing."""
        # Resolve date (safe)
        today = date.today()
        day_text = _safe_str(parsed.get("day_text"), "hari ini")
        meeting_date = resolve_day(day_text, today)
        if not meeting_date:
            await message.reply(f"❌ Tidak bisa menentukan tanggal dari '{day_text}'. Coba: hari ini, besok, senin, selasa, ...")
            return

        # Resolve times (safe — handles string, dict, None)
        start = _safe_time(parsed.get("start_time"), "09:00")
        end = _safe_time(parsed.get("end_time") or parsed.get("duration"), "10:00")
        # If end looks like a duration number (e.g. "30" or "1"), treat as hours
        if end.isdigit():
            try:
                from datetime import datetime as _dt, timedelta as _td
                sh, sm = map(int, start.split(":")[:2])
                start_dt = _dt(2000,1,1,sh,sm)
                end_dt = start_dt + _td(hours=int(end))
                end = f"{end_dt.hour:02d}:{end_dt.minute:02d}"
            except:
                end = "10:00"

        # Convert to UTC
        start_utc = local_to_utc(start)
        end_utc = local_to_utc(end)

        # Validate: reject meetings whose end time is in the past
        meeting_end_dt = f"{meeting_date} {end_utc}"
        if meeting_end_dt < now_str():
            await message.reply("❌ Tidak bisa membuat meeting di masa lalu. Tips: Saat membuat meeting, cantumkan hari, jam mulai, durasi (atau jam selesai), dan channel.")
            return

        # Resolve channel (safe)
        channel = _safe_str(parsed.get("channel"))
        if channel.startswith("#"):
            channel = channel[1:]
        if channel.isdigit():
            try:
                ch_obj = message.guild.get_channel(int(channel))
                if ch_obj:
                    channel = ch_obj.name
            except:
                pass

        # Resolve meeting name
        meeting_name = parsed.get("meeting_name", "Meeting")
        if not meeting_name or meeting_name == "null":
            meeting_name = "Meeting"

        # Extract user IDs from Discord @mentions, LLM response, AND plain name mentions
        raw_user_ids = resolve_mentions(message.content)
        named_ids = resolve_named_mentions(message.content)
        llm_users = parsed.get("users", [])
        llm_ids = [u.get("id", "") for u in llm_users if isinstance(u, dict)]
        all_user_ids = list(set(raw_user_ids + llm_ids + named_ids))

        db = get_db()
        c = db.cursor()
        c.execute(
            "INSERT INTO meetings (name, date, start_time, end_time, channel_id, channel_name, created_by, created_by_name) VALUES (?,?,?,?,?,?,?,?)",
            (meeting_name[:100], meeting_date, start_utc, end_utc, "", channel[:50], str(message.author.id), message.author.name[:50]),
        )
        meeting_id = c.lastrowid

        # Add meeting invites (skip bot's own ID)
        for uid in all_user_ids[:30]:
            if uid == str(self.user.id):
                continue
            real_name = get_real_name(uid)
            c.execute(
                "INSERT INTO meeting_invites (meeting_id, user_id, user_name) VALUES (?,?,?)",
                (meeting_id, uid, real_name),
            )

        db.commit()
        db.close()

        # Format response in local time
        def fmt_time(utc):
            try:
                h, m = map(int, utc.split(":")[:2])
                return f"{(h+7)%24:02d}:{m:02d}"
            except:
                return utc

        day_names_id = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]
        meeting_day = day_names_id[date.fromisoformat(meeting_date).weekday()]

        invited_names = []
        for uid in all_user_ids[:10]:
            if uid == str(self.user.id):
                continue
            name = get_real_name(uid)
            invited_names.append(name)

        reply = f"✅ **{meeting_name}** dijadwalkan!\n"
        reply += f"📅 {meeting_day}, {meeting_date}\n"
        reply += f"🕐 {fmt_time(start_utc)} - {fmt_time(end_utc)} WIB"
        if channel:
            reply += f"\n📍 #{channel}"
        if invited_names:
            reply += f"\n👥 Invited: {", ".join(invited_names) if invited_names else "none"}"
        reply += "\n📌 Creator is always included"
        await message.reply(reply)

    async def handle_edit_meeting(self, message, parsed):
        mid = parsed.get("meeting_id")
        mname = parsed.get("meeting_name")
        changes = parsed.get("changes", {})
        db = get_db()
        if mid:
            meeting = db.execute("SELECT id, name, date, start_time, end_time, channel_id, channel_name FROM meetings WHERE id=? AND cancelled=0", (mid,)).fetchone()
        elif mname:
            # Find by name (today's meetings first)
            meeting = db.execute("SELECT id, name, date, start_time, end_time, channel_id, channel_name FROM meetings WHERE name LIKE ? AND cancelled=0 ORDER BY date DESC LIMIT 1", ('%'+mname+'%',)).fetchone()
        else:
            meeting = None
        if not meeting:
            ref = f"#{mid}" if mid else f'"{mname}"'
            await message.reply(f"❌ Meeting {ref} tidak ditemukan. Coba cek dengan 'meetings today'.")
            db.close(); return
        
        updates = []
        params = []
        if changes.get("time"):
            time_val = changes["time"]
            if isinstance(time_val, dict):
                if time_val.get("start"):
                    updates.append("start_time=?"); params.append(local_to_utc(time_val["start"]))
                if time_val.get("end"):
                    updates.append("end_time=?"); params.append(local_to_utc(time_val["end"]))
            else:
                parts = str(time_val).replace("-"," ").replace("–"," ").split()
                if len(parts) >= 2:
                    updates.append("start_time=?"); params.append(local_to_utc(parts[0]))
                    updates.append("end_time=?"); params.append(local_to_utc(parts[1]))
        if changes.get("channel"):
            updates.append("channel_name=?"); params.append(str(changes["channel"])[:50])
        if changes.get("cancel"):
            db.execute("UPDATE meetings SET cancelled=1 WHERE id=?", (mid,))
            db.commit(); db.close()
            await message.reply(f"❌ Meeting #{mid} ({meeting['name']}) dibatalkan.")
            return
        
        if not updates:
            await message.reply("❓ Tidak ada perubahan yang dikenali. Coba: `ubah meeting 2 ke jam 9-10` atau `pindah meeting 2 ke #UI/UX`")
            db.close(); return
        
        params.append(mid)
        db.execute(f"UPDATE meetings SET {', '.join(updates)} WHERE id=?", params)
        db.commit(); db.close()
        await message.reply(f"✅ Meeting #{mid} ({meeting['name']}) diperbarui.")

    async def handle_list_meetings(self, message, parsed):
        db = get_db()
        period = parsed.get("period", "today")
        if period == "tomorrow" or period == "besok":
            await message.reply("❌ Tidak bisa melihat absen untuk masa depan.")
            db.close(); return
        if period == "yesterday":
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            rows = db.execute(
                "SELECT user_name, absence_type, note FROM absences WHERE date=?",
                (yesterday,),
            ).fetchall()
            if not rows:
                await message.reply(f"✅ Tidak ada yang absen kemarin.")
                db.close(); return
            lines = ["**Absen kemarin:**"]
            for r in rows:
                lines.append(f"  • {r[0]} — {r[1]}")
            await message.reply("\n".join(lines))
            db.close(); return
        if period == "today":
            rows = db.execute(
                "SELECT id, name, start_time, end_time, channel_name, created_by FROM meetings WHERE date=? AND cancelled=0 ORDER BY start_time",
                (today_str(),),
            ).fetchall()
        elif period == "week":
            rows = db.execute(
                "SELECT id, name, date, start_time, end_time, channel_name, created_by FROM meetings WHERE date>=date('now','weekday 0','-6 days') AND cancelled=0 ORDER BY date, start_time"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, name, date, start_time, end_time, channel_name, created_by FROM meetings WHERE cancelled=0 ORDER BY date, start_time LIMIT 10"
            ).fetchall()
        db.close()

        if not rows:
            await message.reply(f"📭 Tidak ada meeting untuk {period}.")
            return

        def add7(t):
            try:
                h,m = map(int, t.split(":")[:2])
                return f"{(h+7)%24:02d}:{m:02d}"
            except:
                return t

        recurring = [r for r in rows if not r["created_by"]]
        onetime = [r for r in rows if r["created_by"]]
        recurring = [r for r in rows if not r["created_by"]]
        onetime = [r for r in rows if r["created_by"]]
        lines = [f"**Meeting {period}:**"]
        def fmt(r):
            ch = r["channel_name"] or ""
            return f'  {r["name"]} [ID:{r["id"]}] | {add7(r["start_time"])}-{add7(r["end_time"])} | {ch}'
        if recurring:
            lines.append("🔁 Recurring:")
            for r in recurring: lines.append(fmt(r))
        if onetime:
            lines.append("📋 One-time:")
            for r in onetime: lines.append(fmt(r))
        lines.append("\nGunakan nomor untuk ubah/cancel. Contoh: ubah ID:1 ke jam 10")
        await message.reply("\n".join(lines))

    async def handle_absent_query(self, message, parsed):
        db = get_db()
        period = parsed.get("period", "today")
        if period == "tomorrow" or period == "besok":
            await message.reply("❌ Tidak bisa melihat absen untuk masa depan.")
            db.close(); return
        if period == "yesterday":
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            rows = db.execute(
                "SELECT user_name, absence_type, note FROM absences WHERE date=?",
                (yesterday,),
            ).fetchall()
            if not rows:
                await message.reply(f"✅ Tidak ada yang absen kemarin.")
                db.close(); return
            lines = ["**Absen kemarin:**"]
            for r in rows:
                lines.append(f"  • {r[0]} — {r[1]}")
            await message.reply("\n".join(lines))
            db.close(); return
        if period == "today":
            rows = db.execute(
                "SELECT user_name, absence_type, note FROM absences WHERE date=?",
                (today_str(),),
            ).fetchall()
        elif period == "week":
            rows = db.execute(
                "SELECT user_name, absence_type, date, note FROM absences WHERE date>=date('now','weekday 0','-6 days') ORDER BY date"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT user_name, absence_type, date, note FROM absences ORDER BY date DESC LIMIT 20"
            ).fetchall()
        db.close()

        if not rows:
            await message.reply(f"✅ Tidak ada yang absen untuk {period}.")
            return

        lines = [f"**Absen {period}:**"]
        for r in rows:
            lines.append(f"  • {r[0]} — {r[1]}" + (f" ({r[2]})" if len(r) > 2 else ""))
        await message.reply("\n".join(lines))

    # ── Voice Tracking ────────────────────────────────
    async def on_voice_state_update(self, member, before, after):
        # Joined a voice channel
        if before.channel is None and after.channel is not None:
            db = get_db()
            db.execute(
                "INSERT INTO voice_sessions (user_id, user_name, channel_id, channel_name, join_time) VALUES (?,?,?,?,?)",
                (str(member.id), str(member)[:50], str(after.channel.id), after.channel.name[:50], now_str()),
            )
            db.commit()
            db.close()
            log.info(f"VOICE JOIN: {member} → {after.channel.name}")

        # Left a voice channel
        elif before.channel is not None and after.channel is None:
            self._close_session(member)
            log.info(f"VOICE LEAVE: {member} ← {before.channel.name}")

        # Moved to a different channel
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            self._close_session(member)
            db = get_db()
            db.execute(
                "INSERT INTO voice_sessions (user_id, user_name, channel_id, channel_name, join_time) VALUES (?,?,?,?,?)",
                (str(member.id), str(member)[:50], str(after.channel.id), after.channel.name[:50], now_str()),
            )
            db.commit()
            db.close()
            log.info(f"VOICE MOVE: {member} {before.channel.name} → {after.channel.name}")

    def _close_session(self, member):
        db = get_db()
        row = db.execute(
            "SELECT id, join_time FROM voice_sessions WHERE user_id=? AND leave_time IS NULL ORDER BY id DESC LIMIT 1",
            (str(member.id),),
        ).fetchone()
        if row:
            join_time = datetime.fromisoformat(row["join_time"])
            duration = int((datetime.utcnow() - join_time).total_seconds() // 60)
            db.execute(
                "UPDATE voice_sessions SET leave_time=?, duration_minutes=? WHERE id=?",
                (now_str(), duration, row["id"]),
            )
        db.commit()
        db.close()

# ── Main ────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    bot = HRBot()
    bot.run(TOKEN)
