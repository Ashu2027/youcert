import os
import sys

# ── Gevent must be patched BEFORE any other import ──────────────
# This file is imported by gunicorn before it spawns workers.
from gevent import monkey
# Patching thread=False keeps compatibility with Flask-MySQLdb
monkey.patch_all(thread=False)

# Ensure flush logging for Cloudflare
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("[wsgi] Booting YOUCERT (Standard Synchronous Loading)...", flush=True)

# Normal synchronous app creation.
# With 1 vCPU and 3GB RAM, this should complete well under Cloudflare's 30s port-bind timeout.
from youcert import create_app

app = create_app()

print("[wsgi] Application loaded and ready to serve requests.", flush=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
