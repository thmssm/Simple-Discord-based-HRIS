#!/usr/bin/env python3
"""HR Dashboard API — your-domain.com"""
import http.server, sqlite3, json, os, hashlib, secrets
from datetime import date, datetime, timedelta

DB = "./hr.db"
PORT = 8081

# === AUTH HELPERS ===

def _hash_password(password, salt=None):
    if not salt:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{h}"

def _verify_password(password, stored):
    try:
        salt, h = stored.split(":", 1)
        return _hash_password(password, salt) == stored
    except:
        return False

def _create_session(username):
    token = secrets.token_hex(32)
    expires = (datetime.utcnow() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    db = sqlite3.connect(DB)
    db.execute('PRAGMA busy_timeout=5000')
    db.execute("INSERT INTO sessions (username, token, expires_at) VALUES (?,?,?)", (username, token, expires))
    db.commit()
    db.close()
    return token

def _get_session(token):
    if not token:
        return None
    db = sqlite3.connect(DB)
    db.execute('PRAGMA busy_timeout=5000')
    row = db.execute("SELECT username FROM sessions WHERE token=? AND expires_at > datetime('now')", (token,)).fetchone()
    db.close()
    return row[0] if row else None

def _delete_session(token):
    db = sqlite3.connect(DB)
    db.execute('PRAGMA busy_timeout=5000')
    db.execute("DELETE FROM sessions WHERE token=?", (token,))
    db.commit()
    db.close()

def query(sql, params=()):
    db = sqlite3.connect(DB)
    db.execute('PRAGMA busy_timeout=5000')
    db.row_factory = sqlite3.Row
    rows = db.execute(sql, params).fetchall()
    db.close()
    return [dict(r) for r in rows]

class API(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Block everything except login unless authenticated
        if self.path == "/api/health":
            self.serve_health()
            return
        if self.path != "/login" and not self.path.startswith("/login?") and self.path != "/api/login":
            if not self._get_session_cookie():
                self._redirect_to_login()
                return
        if self.path == "/login" or self.path.startswith("/login?"):
            self.serve_login_page()
        elif self.path == "/api/logout":
            self.handle_logout()
        elif self.path == "/api/today":
            self.serve_today()
        elif self.path == "/api/attendance":
            self.serve_attendance()
        elif self.path == "/api/schedules":
            self.serve_schedules()
        elif self.path.startswith("/api/schedules/"):
            self.serve_schedule_item()
        elif self.path == "/api/channels":
            self.serve_channels()
        elif self.path == "/api/members":
            self.serve_members()
        elif self.path.startswith("/api/absences"):
            self.serve_absences()
        elif self.path.startswith("/api/message-log"):
            self.serve_message_log()
        elif self.path.startswith("/api/attendance-history"):
            self.serve_attendance_history()
        elif self.path.startswith("/api/calendar"):
            self.serve_calendar()
        elif self.path == "/api/holidays":
            self.serve_holidays()
        elif self.path.startswith("/api/meetings-history"):
            self.serve_meetings_history()
        elif self.path == "/" or self.path == "/index.html":
            self.serve_html()
        elif self.path == "/admin" or self.path == "/admin.html":
            self.serve_admin()
        elif self.path.startswith("/attendance-history"):
            self.serve_attendance_history_page()
        elif self.path.startswith("/absences"):
            self.serve_absences_page()
        elif self.path.startswith("/calendar"):
            self.serve_calendar_page()
        else:
            self.send_error(404)

    def serve_attendance(self):
        today = date.today().isoformat()
        # Per-user summary for today
        users = query("""
            SELECT v.user_name, v.user_id,
                   COUNT(*) as sessions,
                   COALESCE(SUM(v.duration_minutes), 0) as total_minutes,
                   MIN(v.join_time) as first_join,
                   MAX(v.leave_time) as last_leave,
                   COUNT(CASE WHEN v.leave_time IS NULL THEN 1 END) as active_now
            FROM voice_sessions v
            WHERE date(v.join_time)=?
            GROUP BY v.user_id, v.user_name
            ORDER BY total_minutes DESC
        """, (today,))
        # Session details with Python-based meeting matching (SQLite printf unreliable)
        sessions_raw = query("""
            SELECT v.id, v.user_id, v.user_name, v.channel_name, v.join_time, v.leave_time, v.duration_minutes,
                   CASE WHEN v.leave_time IS NULL THEN 1 ELSE 0 END as active
            FROM voice_sessions v
            WHERE date(v.join_time)=?
            ORDER BY v.join_time DESC
        """, (today,))
        meetings = query("SELECT id, name, date, start_time, end_time, channel_name FROM meetings WHERE date=? AND cancelled=0", (today,))
        # Match in Python: time overlap + channel match
        for s in sessions_raw:
            s["meeting_name"] = None
            s["meeting_id"] = None
            jt = s["join_time"]
            lt = s["leave_time"] or "9999-99-99 99:99"
            for m in meetings:
                ms = m["date"] + " " + m["start_time"]
                me = m["date"] + " " + m["end_time"]
                ch = m["channel_name"] or ""
                if (ch == "" or ch == s["channel_name"]) and jt <= me and lt >= ms:
                    s["meeting_name"] = m["name"]
                    s["meeting_id"] = m["id"]
                    break
        # Resolve display names to real names from members table
        members_map = {m["discord_id"]: (m["first_name"] + " " + (m["last_name"] or "")).strip() 
                       for m in query("SELECT discord_id, first_name, last_name FROM members", ())}
        for s in sessions_raw:
            if s["user_id"] in members_map:
                s["display_name"] = s["user_name"]
                s["user_name"] = members_map[s["user_id"]]
        for u in users:
            if u["user_id"] in members_map:
                u["user_name"] = members_map[u["user_id"]]
        sessions = sessions_raw
        self.send_json({"date": today, "users": users, "sessions": sessions})

    def serve_today(self):
        today = date.today().isoformat()
        # Name resolution map
        members_map = {m["discord_id"]: (m["first_name"] + " " + (m["last_name"] or "")).strip()
                       for m in query("SELECT discord_id, first_name, last_name FROM members", ())}
        def resolve_name(uid, name):
            return members_map.get(uid, name)
        # Auto-generate today's meetings from recurring schedules
        holiday_today = query("SELECT 1 FROM holidays WHERE date=?", (today,))
        if not holiday_today:
            today_num = date.today().weekday()
            existing = query("SELECT name FROM meetings WHERE date=?", (today,))
            existing_names = {e["name"] for e in existing}
            schedules = query("SELECT * FROM meeting_schedules WHERE ',' || day_of_week || ',' LIKE '%,' || ? || ',%'", (today_num,))
            db2 = sqlite3.connect(DB)
            db2.execute('PRAGMA busy_timeout=5000')
            db2.row_factory = sqlite3.Row
            for s in schedules:
                if s["name"] not in existing_names:
                    db2.execute(
                        "INSERT INTO meetings (name, date, start_time, end_time, channel_id, channel_name) VALUES (?,?,time(?,?),time(?,?),?,?)",
                        (s["name"], today, s["start_time"], "-7 hours", s["end_time"], "-7 hours", s["channel_id"], s["channel_name"]),
                    )
                    meeting_id = db2.execute("SELECT last_insert_rowid()").fetchone()[0]
                    # Auto-create meeting_invites for assigned schedule members
                    assigned = db2.execute(
                        "SELECT discord_id FROM schedule_members WHERE schedule_id=?", (s["id"],)
                    ).fetchall()
                    for a in assigned:
                        real_name = members_map.get(a["discord_id"], a["discord_id"])
                        db2.execute(
                            "INSERT INTO meeting_invites (meeting_id, user_id, user_name) VALUES (?,?,?)",
                            (meeting_id, a["discord_id"], real_name),
                        )
            db2.commit()
            db2.close()
        data = {
            "date": today,
            "absences": query(
                "SELECT user_name, absence_type, note, original_message FROM absences WHERE date=? ORDER BY id", (today,)
            ),
            "active_voice": query(
                "SELECT user_id, user_name, channel_name, join_time FROM voice_sessions WHERE date(join_time)=? AND leave_time IS NULL ORDER BY channel_name, join_time", (today,)
            ),
            "voice_today": query(
                "SELECT user_id, user_name, channel_name, join_time, leave_time, duration_minutes FROM voice_sessions WHERE date(join_time)=? AND leave_time IS NOT NULL ORDER BY join_time DESC LIMIT 20", (today,)
            ),
            "upcoming_meetings": query(
                "SELECT id, name, start_time, end_time, channel_name, "
                "CASE WHEN datetime(date || ' ' || end_time, '+7 hours') < datetime('now') THEN 'concluded' ELSE 'upcoming' END as status "
                "FROM meetings WHERE date=? AND cancelled=0 ORDER BY start_time", (today,)
            ),
            "stats": {
                "total_voice_sessions": len(query("SELECT id FROM voice_sessions WHERE date(join_time)=?", (today,))),
                "active_now": len(query("SELECT id FROM voice_sessions WHERE leave_time IS NULL")),
            }
        }
        # Resolve names
        for v in data["active_voice"]:
            v["user_name"] = resolve_name(v.get("user_id",""), v["user_name"])
        for v in data["voice_today"]:
            v["user_name"] = resolve_name(v.get("user_id",""), v["user_name"])
        self.send_json(data)

    def _get_session_cookie(self):
        """Extract session token from Cookie header, return username or None."""
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split("; "):
            if part.startswith("session="):
                return _get_session(part.split("=", 1)[1])
        return None

    def _redirect_to_login(self):
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()

    def serve_health(self):
        """Health check — returns bot status based on heartbeat."""
        import subprocess, sqlite3
        db = sqlite3.connect(DB)
        db.execute('PRAGMA busy_timeout=5000')
        row = db.execute("SELECT timestamp FROM bot_heartbeat ORDER BY id DESC LIMIT 1").fetchone()
        db.close()
        if row:
            last = row[0]
            age_sec = (datetime.utcnow() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).total_seconds()
            bot_alive = age_sec < 90
        else:
            age_sec = None
            bot_alive = False
        
        # Check systemd service status
        svc = subprocess.run(["systemctl", "is-active", "hr-bot.service"], capture_output=True, text=True)
        svc_status = svc.stdout.strip()
        
        self.send_json({
            "bot": "alive" if bot_alive else "dead",
            "last_heartbeat_sec_ago": age_sec,
            "service": svc_status,
            "dashboard": "alive"
        })

    def serve_html(self):
        html = open("./dashboard.html").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_admin(self):
        html = open("./admin.html").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_attendance_history_page(self):
        html = open("./attendance-history.html").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_absences_page(self):
        html = open("./absences.html").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_calendar_page(self):
        html = open("./calendar.html").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())
    def send_json(self, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_json_status(self, data, status):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # silence logs

    def do_POST(self):
        if self.path == "/api/login":
            self.handle_login()
        elif self.path == "/api/logout":
            self.handle_logout()
        elif self.path.startswith("/api/schedules"):
            if not self._require_auth(): return
            self.handle_schedule_post()
        elif self.path == "/api/members":
            if not self._require_auth(): return
            self.handle_member_post()
        elif self.path == "/api/channels/refresh":
            if not self._require_auth(): return
            import subprocess
            subprocess.run(["sudo", "systemctl", "restart", "hr-bot"], capture_output=True)
            self.send_json({"ok": True})
        elif self.path == "/api/holidays":
            if not self._require_auth(): return
            self.handle_holiday_post()
        else:
            self.send_error(404)

    def _require_auth(self):
        if not self._get_session_cookie():
            self.send_json_status({"error": "Unauthorized"}, 403)
            return False
        return True

    def serve_login_page(self):
        html = open("./login.html", "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html)

    def handle_login(self):
        # Cleanup expired sessions and old login attempts periodically
        client_ip = self.client_address[0]
        db = sqlite3.connect(DB)
        db.execute('PRAGMA busy_timeout=5000')
        db.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
        db.execute("DELETE FROM login_attempts WHERE attempt_time < datetime('now','-1 hour')")
        db.commit()
        # Rate limit: max 5 attempts per minute per IP
        recent = db.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip=? AND attempt_time > datetime('now','-1 minute')",
            (client_ip,)
        ).fetchone()[0]
        if recent >= 5:
            db.close()
            self.send_response(429)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Too many attempts. Wait 1 minute.")
            return
        db.execute("INSERT INTO login_attempts (ip) VALUES (?)", (client_ip,))
        db.commit()
        
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        if self.headers.get("Content-Type", "").startswith("application/json"):
            body = json.loads(raw)
            username = body.get("username", "")
            password = body.get("password", "")
            turnstile_token = body.get("cf-turnstile-response", "")
        else:
            from urllib.parse import parse_qs
            body = parse_qs(raw.decode())
            username = body.get("username", [""])[0]
            password = body.get("password", [""])[0]
            turnstile_token = body.get("cf-turnstile-response", [""])[0]
        
        # Verify Turnstile with Cloudflare (skip for localhost)
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            secret = "REVOKED_CLOUDFLARE_TURNSTILE_SECRET"
            import urllib.request as ur, urllib.parse as up
            verify_data = up.urlencode({"secret": secret, "response": turnstile_token}).encode()
            verify_req = ur.Request("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=verify_data)
            try:
                verify_resp = json.loads(ur.urlopen(verify_req, timeout=5).read())
                if not verify_resp.get("success"):
                    db.close()
                    self.send_response(302)
                    self.send_header("Location", "/login?error=2")
                    self.end_headers()
                    return
            except:
                db.close()
                self.send_response(302)
                self.send_header("Location", "/login?error=2")
                self.end_headers()
                return
        
        row = db.execute("SELECT password_hash FROM credentials WHERE username=?", (username,)).fetchone()
        db.close()
        if row and _verify_password(password, row[0]):
            token = _create_session(username)
            self.send_response(302)
            self.send_header("Set-Cookie", f"session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400")
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self.send_response(302)
            self.send_header("Location", "/login?error=1")
            self.end_headers()

    def handle_logout(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split("; "):
            if part.startswith("session="):
                _delete_session(part.split("=", 1)[1])
        self.send_response(302)
        self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0")
        self.send_header("Location", "/login")
        self.end_headers()

    def handle_schedule_post(self):
        import json as j
        length = int(self.headers.get("Content-Length", 0))
        body = j.loads(self.rfile.read(length))
        action = body.get("action", "")
        db = sqlite3.connect(DB)
        db.execute('PRAGMA busy_timeout=5000')
        if action == "create":
            db.execute(
                "INSERT INTO meeting_schedules (name, day_of_week, start_time, end_time, channel_id, channel_name) VALUES (?,?,?,?,?,?)",
                (body["name"], str(body["day"]), body["start"], body["end"], body.get("channel_id",""), body.get("channel_name",""))
            )
            sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Save assigned members
            members = body.get("members", [])
            for discord_id in members:
                db.execute(
                    "INSERT OR IGNORE INTO schedule_members (schedule_id, discord_id) VALUES (?,?)",
                    (sid, discord_id),
                )
            db.commit()
            self.send_json({"ok": True, "id": sid})
        elif action == "update":
            db.execute(
                "UPDATE meeting_schedules SET name=?, day_of_week=?, start_time=?, end_time=?, channel_id=?, channel_name=? WHERE id=?",
                (body["name"], str(body["day"]), body["start"], body["end"], body.get("channel_id",""), body.get("channel_name",""), body["id"])
            )
            # Replace assigned members
            db.execute("DELETE FROM schedule_members WHERE schedule_id=?", (body["id"],))
            members = body.get("members", [])
            for discord_id in members:
                db.execute(
                    "INSERT OR IGNORE INTO schedule_members (schedule_id, discord_id) VALUES (?,?)",
                    (body["id"], discord_id),
                )
            db.commit()
            self.send_json({"ok": True})
        elif action == "delete":
            db.execute("DELETE FROM meeting_schedules WHERE id=?", (body["id"],))
            db.execute("DELETE FROM schedule_members WHERE schedule_id=?", (body["id"],))
            db.commit()
            self.send_json({"ok": True})
        else:
            self.send_error(400)
        db.close()

    def serve_schedules(self):
        rows = query("SELECT id, name, day_of_week, start_time, end_time, channel_id, channel_name FROM meeting_schedules ORDER BY day_of_week, start_time")
        # Attach assigned members to each schedule
        db = sqlite3.connect(DB)
        db.execute('PRAGMA busy_timeout=5000')
        db.row_factory = sqlite3.Row
        for s in rows:
            members = db.execute(
                "SELECT discord_id FROM schedule_members WHERE schedule_id=?", (s["id"],)
            ).fetchall()
            s["members"] = [m["discord_id"] for m in members]
        db.close()
        self.send_json(list(rows))

    def serve_schedule_item(self):
        import re
        m = re.search(r"/api/schedules/(\d+)", self.path)
        if m:
            rows = query("SELECT * FROM meeting_schedules WHERE id=?", (int(m.group(1)),))
            if rows:
                row = rows[0]
                db = sqlite3.connect(DB)
                db.execute('PRAGMA busy_timeout=5000')
                db.row_factory = sqlite3.Row
                members = db.execute(
                    "SELECT discord_id FROM schedule_members WHERE schedule_id=?", (row["id"],)
                ).fetchall()
                row["members"] = [m["discord_id"] for m in members]
                db.close()
                self.send_json(row)
            else:
                self.send_error(404)
        else:
            self.send_error(400)

    def serve_channels(self):
        rows = query("SELECT channel_name FROM channels ORDER BY channel_name")
        self.send_json([r["channel_name"] for r in rows])

    def serve_members(self):
        rows = query("SELECT id, discord_id, discord_name, first_name, last_name, nickname, gender, role, division_id, active FROM members ORDER BY first_name")
        self.send_json(list(rows))

    def serve_calendar(self):
        from urllib.parse import urlparse, parse_qs
        from calendar import monthrange
        qs = parse_qs(urlparse(self.path).query)
        month_str = qs.get("month", [None])[0] or date.today().strftime("%Y-%m")
        year, month = int(month_str[:4]), int(month_str[5:7])
        _, days_in_month = monthrange(year, month)
        
        # Get all meetings in this month
        month_start = f"{year}-{month:02d}-01"
        month_end = f"{year}-{month:02d}-{days_in_month}"
        meetings = query("""
            SELECT id, name, date, start_time, end_time, channel_name
            FROM meetings WHERE cancelled=0 AND date>=? AND date<=?
            ORDER BY date, start_time
        """, (month_start, month_end))
        
        # Get schedules for display
        schedules = query("""
            SELECT id, name, day_of_week, start_time, end_time, channel_name
            FROM meeting_schedules ORDER BY day_of_week, start_time
        """)
        
        # Get holidays
        holidays = query("""
            SELECT id, date, name FROM holidays WHERE date>=? AND date<=?
            ORDER BY date
        """, (month_start, month_end))
        
        self.send_json({
            "year": year, "month": month,
            "days_in_month": days_in_month,
            "first_weekday": date(year, month, 1).weekday(),
            "meetings": list(meetings),
            "schedules": list(schedules),
            "holidays": list(holidays),
        })

    def serve_holidays(self):
        rows = query("SELECT id, date, name FROM holidays ORDER BY date")
        self.send_json(list(rows))

    def handle_holiday_post(self):
        import json as j
        length = int(self.headers.get("Content-Length", 0))
        body = j.loads(self.rfile.read(length))
        action = body.get("action", "")
        db = sqlite3.connect(DB)
        db.execute('PRAGMA busy_timeout=5000')
        if action == "add":
            db.execute("INSERT OR IGNORE INTO holidays (date, name) VALUES (?,?)",
                       (body["date"], body["name"][:100]))
        elif action == "update":
            db.execute("UPDATE holidays SET date=?, name=? WHERE id=?",
                       (body["date"], body["name"][:100], body["id"]))
        elif action == "delete":
            db.execute("DELETE FROM holidays WHERE id=?", (body["id"],))
        db.commit()
        db.close()
        self.send_json({"ok": True})

    def serve_message_log(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        req_date = qs.get("date", [None])[0] or date.today().isoformat()
        
        members_map = {m["discord_id"]: (m["first_name"] + " " + (m["last_name"] or "")).strip()
                       for m in query("SELECT discord_id, first_name, last_name FROM members", ())}
        
        rows = query("""
            SELECT id, user_id, user_name, content, llm_intent, llm_absence_type, parsed_date, parsed_note, created_at
            FROM message_log WHERE date(created_at)=?
            ORDER BY created_at DESC
        """, (req_date,))
        
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "user_name": members_map.get(r["user_id"], r["user_name"]),
                "content": r["content"],
                "llm_intent": r["llm_intent"],
                "absence_type": r["llm_absence_type"],
                "parsed_note": r["parsed_note"],
                "created_at": r["created_at"],
            })
        self.send_json(result)

    def serve_absences(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        req_date = qs.get("date", [None])[0]
        page = int(qs.get("page", [0])[0])
        per_page = int(qs.get("per_page", [50])[0])
        
        members_map = {m["discord_id"]: (m["first_name"] + " " + (m["last_name"] or "")).strip()
                       for m in query("SELECT discord_id, first_name, last_name FROM members", ())}
        
        if req_date:
            count = query("SELECT COUNT(*) as c FROM absences WHERE date=?", (req_date,))[0]["c"]
            rows = query("""
                SELECT a.id, a.user_id, a.user_name, a.absence_type, a.date, a.note, a.original_message, a.created_at
                FROM absences a WHERE a.date=?
                ORDER BY a.created_at DESC LIMIT ? OFFSET ?
            """, (req_date, per_page, page * per_page))
        else:
            count = query("SELECT COUNT(*) as c FROM absences", ())[0]["c"]
            rows = query("""
                SELECT a.id, a.user_id, a.user_name, a.absence_type, a.date, a.note, a.original_message, a.created_at
                FROM absences a ORDER BY a.date DESC, a.created_at DESC LIMIT ? OFFSET ?
            """, (per_page, page * per_page))
        
        items = []
        for r in rows:
            items.append({
                "id": r["id"], "date": r["date"],
                "user_name": members_map.get(r["user_id"], r["user_name"]),
                "absence_type": r["absence_type"],
                "note": r["note"],
                "original_message": r["original_message"],
                "created_at": r["created_at"],
            })
        self.send_json({"items": items, "total": count})

    def serve_attendance_history(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        req_date = qs.get("date", [None])[0] or date.today().isoformat()
        
        members_map = {m["discord_id"]: (m["first_name"] + " " + (m["last_name"] or "")).strip()
                       for m in query("SELECT discord_id, first_name, last_name FROM members WHERE active=1", ())}
        
        # Check if this date is a holiday
        holiday = query("SELECT name FROM holidays WHERE date=?", (req_date,))
        is_holiday = bool(holiday)
        holiday_name = holiday[0]["name"] if holiday else None
        
        # Check if weekend (Saturday=5, Sunday=6)
        req_date_obj = date.fromisoformat(req_date)
        is_weekend = req_date_obj.weekday() >= 5
        is_future = req_date_obj > date.today()
        
        # Future dates: return summary only, no member list
        if is_future:
            self.send_json({"future": True, "date": req_date, "message": "This date has not occurred yet"})
            return
        
        # Get all absences for this date
        absences = {a["user_id"]: {"type": a["absence_type"], "note": a["note"]}
                    for a in query("SELECT user_id, user_name, absence_type, note FROM absences WHERE date=?", (req_date,))}
        
        # Get all voice sessions for this date
        sessions = query("""
            SELECT v.id, v.user_id, v.user_name, v.channel_name, v.join_time, v.leave_time, v.duration_minutes,
                   CASE WHEN v.leave_time IS NULL THEN 1 ELSE 0 END as active
            FROM voice_sessions v
            WHERE date(v.join_time)=?
            ORDER BY v.join_time
        """, (req_date,))
        
        # Group sessions by user
        user_sessions = {}
        for s in sessions:
            uid = s["user_id"]
            if uid not in user_sessions:
                user_sessions[uid] = []
            user_sessions[uid].append(s)
        
        # Build result for all active members
        result = []
        for discord_id, real_name in sorted(members_map.items(), key=lambda x: x[1].lower()):
            entry = {
                "user_id": discord_id,
                "user_name": real_name,
                "status": "missing",
                "status_label": "Missing",
                "first_join": None,
                "last_leave": None,
                "total_minutes": 0,
                "sessions": [],
                "absence": None,
            }
            
            # Check absence
            if discord_id in absences:
                ab = absences[discord_id]
                entry["absence"] = {"type": ab["type"], "note": ab["note"]}
                # Map absence type to status
                type_map = {"sick": "sick", "day_off": "off", "paid_leave": "leave", "afk": "afk"}
                entry["status"] = type_map.get(ab["type"], "off")
                entry["status_label"] = ab["type"].replace("_", " ").title()
            
            # Check voice sessions
            if discord_id in user_sessions:
                us = user_sessions[discord_id]
                entry["sessions"] = [{
                    "channel_name": s["channel_name"],
                    "join_time": s["join_time"],
                    "leave_time": s["leave_time"],
                    "duration_minutes": s["duration_minutes"],
                    "active": bool(s["active"]),
                } for s in us]
                
                total = sum(s["duration_minutes"] or 0 for s in us)
                entry["total_minutes"] = total
                entry["first_join"] = us[0]["join_time"]
                
                # Last leave (use latest non-null, or None if still active)
                leaves = [s["leave_time"] for s in us if s["leave_time"]]
                entry["last_leave"] = leaves[-1] if leaves else None
                
            # Determine status
            if entry["absence"]:
                pass  # already set from absence
            elif is_future:
                entry["status"] = "future"
                entry["status_label"] = "Future"
            elif is_holiday and not entry["sessions"]:
                entry["status"] = "holiday"
                entry["status_label"] = "Holiday"
            elif is_weekend and not entry["sessions"]:
                entry["status"] = "weekend"
                entry["status_label"] = "Weekend"
            elif entry["sessions"]:
                # Extract hour from first join
                try:
                    time_part = us[0]["join_time"].split(" ")[1]
                    first_hour = int(time_part.split(":")[0])
                    local_hour = (first_hour + 7) % 24
                    if local_hour >= 10:
                        entry["status"] = "late"
                        entry["status_label"] = "Late"
                    else:
                        entry["status"] = "present"
                        entry["status_label"] = "Present"
                except:
                    entry["status"] = "present"
                    entry["status_label"] = "Present"
            
            result.append(entry)
        
        self.send_json(result)

    def serve_meetings_history(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        req_date = qs.get("date", [None])[0] or date.today().isoformat()
        # Get concluded meetings for the requested date
        meetings = query("""
            SELECT m.id, m.name, m.date, m.start_time, m.end_time, m.channel_name,
                   m.created_by, m.created_by_name,
                   datetime('now') > datetime(m.date || ' ' || m.end_time) as concluded
            FROM meetings m
            WHERE m.cancelled = 0 AND m.date = ?
            ORDER BY m.start_time
            LIMIT 50
        """, (req_date,))
        
        result = []
        # Name resolution
        members_map = {m["discord_id"]: (m["first_name"] + " " + (m["last_name"] or "")).strip()
                       for m in query("SELECT discord_id, first_name, last_name FROM members", ())}
        for m in meetings:
            # Fetch ALL voice sessions in the meeting channel on that date
            # that overlap with the meeting window (with generous molor buffer)
            sessions = query("""
                SELECT v.user_id, v.user_name, v.join_time, v.leave_time, v.duration_minutes
                FROM voice_sessions v
                WHERE date(v.join_time) = ?
                  AND v.channel_name = ?
                  AND v.join_time <= datetime(? || ' ' || ?, '+2 hours')
                  AND (v.leave_time IS NULL OR v.leave_time >= ? || ' ' || ?)
                ORDER BY v.join_time
            """, (m["date"], m["channel_name"], m["date"], m["end_time"], m["date"], m["start_time"]))
            
            # Calculate actual overlap duration with "molor" end
            meet_start = m["date"] + " " + m["start_time"]
            meet_end_scheduled = m["date"] + " " + m["end_time"]
            
            # Find actual meeting end: latest leave time in the session group
            # that started within 2h of scheduled end (captures molor)
            actual_end = meet_end_scheduled
            for s in sessions:
                if s["leave_time"] and s["leave_time"] > actual_end:
                    actual_end = s["leave_time"]
            
            # Calculate per-user overlap minutes
            from datetime import datetime as dt
            attendee_minutes = {}
            for s in sessions:
                sess_start = s["join_time"]
                sess_end = s["leave_time"] or now_str()
                overlap_start = max(sess_start, meet_start)
                overlap_end = min(sess_end, actual_end)
                if overlap_start < overlap_end:
                    try:
                        start_dt = dt.fromisoformat(overlap_start)
                        end_dt = dt.fromisoformat(overlap_end)
                        overlap_min = int((end_dt - start_dt).total_seconds() // 60)
                    except:
                        overlap_min = s["duration_minutes"] or 0
                    if s["user_id"] not in attendee_minutes:
                        attendee_minutes[s["user_id"]] = {"user_name": members_map.get(s["user_id"], s["user_name"]), "total_min": 0}
                    attendee_minutes[s["user_id"]]["total_min"] += overlap_min
            
            # Build sorted attendees list
            attendees = sorted(attendee_minutes.values(), key=lambda a: a["total_min"], reverse=True)
            total_duration = sum(a["total_min"] for a in attendees)
            
            for a in attendees:
                # Attach user_id for reference
                for uid, data in attendee_minutes.items():
                    if data["user_name"] == a["user_name"]:
                        a["user_id"] = uid
                        break
            
            result.append({
                "id": m["id"], "name": m["name"], "date": m["date"],
                "start_time": m["start_time"], "end_time": m["end_time"],
                "channel_name": m["channel_name"], "concluded": bool(m["concluded"]),
                "is_recurring": m["created_by"] is None,
                "created_by_name": m["created_by_name"],
                "total_attendees": len(attendees),
                "total_duration": total_duration,
                "attendees": [{"user_name": a["user_name"], 
                               "total_min": a["total_min"]} for a in attendees],
                "invited": [],
                "absent": [],
            })
            # Fetch meeting invites
            invites = query(
                "SELECT user_id, user_name FROM meeting_invites WHERE meeting_id=?", (m["id"],)
            )
            if invites:
                attended_ids = {a.get("user_id", "") for a in attendees}
                invited_list = []
                absent_list = []
                for inv in invites:
                    name = members_map.get(inv["user_id"], inv["user_name"])
                    if inv["user_id"] in attended_ids:
                        invited_list.append(name)
                    else:
                        absent_list.append(name)
                if invited_list:
                    result[-1]["invited"] = invited_list
                if absent_list:
                    result[-1]["absent"] = absent_list
        
        self.send_json(result)

    def handle_member_post(self):
        import json as j
        length = int(self.headers.get("Content-Length", 0))
        body = j.loads(self.rfile.read(length))
        action = body.get("action", "")
        db = sqlite3.connect(DB)
        db.execute('PRAGMA busy_timeout=5000')
        if action == "add":
            did = body.get("discord_id","") or None
            db.execute(
                "INSERT INTO members (discord_id, discord_name, first_name, last_name, nickname, gender, role) VALUES (?,?,?,?,?,?,?)",
                (did, body.get("discord_name",""), body["first_name"], body.get("last_name",""), body.get("nickname",""), body.get("gender",""), body.get("role",""))
            )
            db.commit()
            self.send_json({"ok": True})
        elif action == "update":
            db.execute(
                "UPDATE members SET discord_id=?, discord_name=?, first_name=?, last_name=?, nickname=?, gender=?, role=?, active=? WHERE id=?",
                (body.get("discord_id",""), body.get("discord_name",""), body["first_name"], body.get("last_name",""), body.get("nickname",""), body.get("gender",""), body.get("role",""), body.get("active",1), body["id"])
            )
            db.commit()
            self.send_json({"ok": True})
        elif action == "delete":
            db.execute("DELETE FROM members WHERE id=?", (body["id"],))
            db.commit()
            self.send_json({"ok": True})
        else:
            self.send_error(400)
        db.close()

if __name__ == "__main__":
    http.server.HTTPServer(("127.0.0.1", PORT), API).serve_forever()
