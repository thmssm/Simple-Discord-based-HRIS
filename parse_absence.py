#!/usr/bin/env python3
"""CLI tool to test absence parsing via DeepSeek.

Usage: python3 parse_absence.py "izin sakit hari ini"
Requires DEEPSEEK_API_KEY env var.
"""
import json, urllib.request, os, re, sys
from datetime import datetime, timezone, timedelta

key = os.environ.get("DEEPSEEK_API_KEY", "")
if not key:
    print("ERROR: Set DEEPSEEK_API_KEY environment variable")
    sys.exit(1)

text = sys.argv[1] if len(sys.argv) > 1 else ""
if not text:
    print("Usage: python3 parse_absence.py <message>")
    sys.exit(1)

today = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")

prompt = (
    'Parse employee absence message. '
    'Return valid JSON with these fields: '
    'intent ("report_absence" or "ignore"), '
    'absence_type ("day_off","sick","afk","paid_leave","other"), '
    f'date (YYYY-MM-DD, today is {today}), '
    'note (brief reason). '
    'Message: "' + text + '"'
)

data = json.dumps({
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 150,
    "temperature": 0,
}).encode()

req = urllib.request.Request(
    "https://api.deepseek.com/v1/chat/completions",
    data=data,
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
)

with urllib.request.urlopen(req, timeout=10) as r:
    result = json.loads(r.read())

content = result["choices"][0]["message"]["content"].strip()
if content.startswith("```"):
    content = re.sub(r"^```(?:json)?\n", "", content)
    content = re.sub(r"\n```$", "", content)

parsed = json.loads(content)
print(json.dumps(parsed, indent=2, ensure_ascii=False))
