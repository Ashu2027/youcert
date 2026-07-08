"""
Cloudflare Container Log Analyzer
Reads the full JSON log file and produces a comprehensive report of:
  - All unique errors and exceptions
  - HTTP status code breakdown
  - Warning patterns
  - Top error messages by frequency
  - Timeline of events
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
import glob
import os

# ── find the log file ──────────────────────────────────────────────────────────
LOG_PATTERNS = [
    "logs-*.json",
    "*.json",
]

def find_log_file():
    for pattern in LOG_PATTERNS:
        matches = glob.glob(pattern)
        # prefer files that look like log dumps
        log_matches = [m for m in matches if "logs-" in m or "log" in m.lower()]
        if log_matches:
            return sorted(log_matches)[-1]  # latest
        if matches:
            return matches[0]
    return None

# ── load log ───────────────────────────────────────────────────────────────────
log_file = sys.argv[1] if len(sys.argv) > 1 else find_log_file()
if not log_file or not os.path.exists(log_file):
    print("❌  No log file found. Usage: python analyze_logs.py <log_file.json>")
    sys.exit(1)

print(f"\n📂  Analyzing: {log_file}")
print(f"    Size: {os.path.getsize(log_file) / 1024:.1f} KB\n")

with open(log_file, "r", encoding="utf-8") as f:
    logs = json.load(f)

print(f"📊  Total log entries: {len(logs)}\n")

# ── collectors ─────────────────────────────────────────────────────────────────
http_status_counter   = Counter()   # {200: N, 404: N, ...}
http_errors           = []          # list of (ts, method, path, status)
python_errors         = []          # list of (ts, msg)
python_warnings       = []          # list of (ts, msg)
unique_exceptions     = {}          # exception_type -> {msg, count, first_seen}
unique_errors         = {}          # error_text -> count
error_freq            = Counter()
route_access          = Counter()
timestamps            = []

ACCESS_LOG_RE = re.compile(
    r'"(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS) ([^ ]+) HTTP[^"]*" (\d{3})'
)
PYTHON_LOG_RE = re.compile(
    r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ - \w+ - (ERROR|WARNING|CRITICAL|INFO) - (.+?)(?:\s*\|.*)?$'
)
EXCEPTION_RE  = re.compile(r'([A-Za-z]+(?:Exception|Error)): (.+)')
ERROR_CODE_RE = re.compile(r'"code":\s*(\d+)')

for entry in logs:
    meta = entry.get("$metadata", {})
    msg  = meta.get("message", "")
    ts   = entry.get("timestamp", "")[:19]  # 2026-03-05T05:40:22
    level = meta.get("level", "info")

    # ── HTTP access log lines ──
    m = ACCESS_LOG_RE.search(msg)
    if m:
        method, path, status_str = m.group(1), m.group(2), m.group(3)
        status = int(status_str)
        http_status_counter[status] += 1
        route_access[f"{method} {path.split('?')[0]}"] += 1
        if status >= 400:
            http_errors.append((ts, method, path, status))
        continue   # access log lines have no Python log level

    # ── Python structured log lines ──
    pm = PYTHON_LOG_RE.search(msg)
    if pm:
        log_level, log_msg = pm.group(1), pm.group(2).strip()

        if log_level in ("ERROR", "CRITICAL"):
            python_errors.append((ts, log_level, log_msg))
            error_freq[log_msg[:120]] += 1

        elif log_level == "WARNING":
            python_warnings.append((ts, log_msg))
        continue

    # ── Raw exception / traceback lines ──
    em = EXCEPTION_RE.search(msg)
    if em:
        exc_type, exc_msg = em.group(1), em.group(2).strip()
        key = exc_type
        if key not in unique_exceptions:
            unique_exceptions[key] = {"msg": exc_msg[:200], "count": 0, "first_seen": ts}
        unique_exceptions[key]["count"] += 1

    # ── Cloudflare API error codes ──
    for code in ERROR_CODE_RE.findall(msg):
        error_freq[f"CF API error_code={code}"] += 1

# ══════════════════════════════════════════════════════════════════════════════
# REPORT
# ══════════════════════════════════════════════════════════════════════════════

SEP  = "=" * 72
SEP2 = "-" * 72

print(SEP)
print("  CLOUDFLARE CONTAINER LOG — FULL ANALYSIS REPORT")
print(SEP)

# ── 1. HTTP Status Code Summary ───────────────────────────────────────────────
print("\n📈  HTTP STATUS CODE BREAKDOWN\n" + SEP2)
for status in sorted(http_status_counter):
    bar   = "█" * min(http_status_counter[status], 40)
    emoji = "✅" if status < 400 else ("🟡" if status < 500 else "🔴")
    print(f"  {emoji}  {status}  {bar}  ({http_status_counter[status]:,} requests)")

# ── 2. HTTP Errors (4xx / 5xx) ────────────────────────────────────────────────
if http_errors:
    print(f"\n🔴  HTTP 4xx/5xx ERRORS ({len(http_errors)} total)\n" + SEP2)
    seen_http = set()
    for ts, method, path, status in sorted(http_errors, key=lambda x: x[3], reverse=True):
        key = f"{method} {path.split('?')[0]} {status}"
        if key not in seen_http:
            seen_http.add(key)
            print(f"  [{ts}]  {status}  {method:6}  {path[:80]}")

# ── 3. Python ERROR / CRITICAL messages ──────────────────────────────────────
print(f"\n🔴  PYTHON ERRORS & CRITICAL MESSAGES ({len(python_errors)} total)\n" + SEP2)
if python_errors:
    seen_err = set()
    for ts, lvl, msg in python_errors:
        key = msg[:100]
        if key not in seen_err:
            seen_err.add(key)
            print(f"  [{ts}]  [{lvl}]  {msg[:110]}")
else:
    print("  None found ✅")

# ── 4. Python WARNING messages ────────────────────────────────────────────────
print(f"\n🟡  PYTHON WARNINGS ({len(python_warnings)} total)\n" + SEP2)
if python_warnings:
    seen_warn = set()
    for ts, msg in python_warnings:
        if msg[:100] not in seen_warn:
            seen_warn.add(msg[:100])
            print(f"  [{ts}]  {msg[:110]}")
else:
    print("  None found ✅")

# ── 5. Exception Types ────────────────────────────────────────────────────────
if unique_exceptions:
    print(f"\n💥  EXCEPTION TYPES FOUND\n" + SEP2)
    for exc_type, info in sorted(unique_exceptions.items(), key=lambda x: -x[1]["count"]):
        print(f"  🔸  {exc_type}  (×{info['count']})")
        print(f"        First seen: {info['first_seen']}")
        print(f"        Message:    {info['msg'][:100]}")
        print()

# ── 6. Top Error Messages by Frequency ───────────────────────────────────────
print(f"\n📊  TOP 20 ERROR MESSAGES BY FREQUENCY\n" + SEP2)
for msg, count in error_freq.most_common(20):
    print(f"  ×{count:4d}  {msg[:100]}")

# ── 7. Most Accessed Routes ───────────────────────────────────────────────────
print(f"\n🌐  TOP 15 ROUTES BY REQUEST COUNT\n" + SEP2)
for route, count in route_access.most_common(15):
    print(f"  {count:5d}×  {route[:80]}")

# ── 8. Summary Card ───────────────────────────────────────────────────────────
total_4xx = sum(v for k, v in http_status_counter.items() if 400 <= k < 500)
total_5xx = sum(v for k, v in http_status_counter.items() if k >= 500)
total_2xx = sum(v for k, v in http_status_counter.items() if 200 <= k < 300)

print(f"\n{SEP}")
print("  SUMMARY CARD")
print(SEP)
print(f"  Total log entries         : {len(logs):,}")
print(f"  HTTP 2xx (success)        : {total_2xx:,}")
print(f"  HTTP 4xx (client errors)  : {total_4xx:,}")
print(f"  HTTP 5xx (server errors)  : {total_5xx:,}")
print(f"  Python ERROR/CRITICAL msgs: {len(python_errors):,}")
print(f"  Python WARNING msgs       : {len(python_warnings):,}")
print(f"  Unique exception types    : {len(unique_exceptions):,}")
print(f"  Unique error patterns     : {len(error_freq):,}")
print(SEP)
print("\n✅  Analysis complete.\n")
