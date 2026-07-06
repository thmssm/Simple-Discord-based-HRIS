#!/usr/bin/env python3
"""Watchdog — checks bot health every 5 min, appends to bot.log."""
import sqlite3, subprocess, sys
from datetime import datetime, timedelta

DB = os.environ.get("HRBOT_DB_PATH", "hr.db")
LOG = os.environ.get("HRBOT_LOG_PATH", "bot.log")

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

db = sqlite3.connect(DB)
db.execute("PRAGMA busy_timeout=5000")
row = db.execute("SELECT timestamp FROM bot_heartbeat ORDER BY id DESC LIMIT 1").fetchone()
db.close()

if row:
    last = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    age_sec = (datetime.utcnow() - last).total_seconds()
    alive = age_sec < 120  # 2 min grace period
else:
    age_sec = None
    alive = False

SERVICE_NAME = os.environ.get("HRBOT_SERVICE", "hr-bot.service")
svc = subprocess.run(["systemctl", "is-active", SERVICE_NAME], capture_output=True, text=True)
svc_status = svc.stdout.strip()

if alive:
    status = f"[WATCHDOG] Bot HEALTHY | heartbeat {int(age_sec)}s ago | service={svc_status}"
else:
    status = f"[WATCHDOG] Bot UNHEALTHY | heartbeat {'STALE' if age_sec else 'MISSING'} | service={svc_status}"

with open(LOG, "a") as f:
    f.write(f"{now()} [INFO] {status}\n")

# If unhealthy for too long, also flag to stderr for journal
if not alive and (age_sec is None or age_sec > 300):
    print(f"CRITICAL: Bot appears dead — last heartbeat {age_sec}s ago, service={svc_status}", file=sys.stderr)
