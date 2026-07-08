# =====================================================================
# YOUCERT — Dockerfile for Cloudflare Containers
# =====================================================================
# This container uses a synchronous WSGI startup under Gunicorn.
# The 3GB/1vCPU instance type ensures the app finishes booting
# well within Cloudflare's 30-second port binding timeout.

FROM python:3.12-slim

# ── System dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    libjpeg-dev \
    libpng-dev \
    libffi-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user (security hardening) ──────────────────────────────
RUN useradd --create-home --shell /bin/bash youcert
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────
COPY --chown=youcert:youcert . .

# ── Runtime environment ──────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IS_DEVELOPMENT=false \
    PORT=8080

# ── Switch to non-root user ──────────────────────────────────────────
USER youcert

EXPOSE 8080

# ── Start command ────────────────────────────────────────────────────
# gevent worker: 1 worker process + 50 greenlet connections = 50 concurrent
# This prevents 0.25 vCPU starvation and forces Cloudflare to scale horizontally.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--worker-class", "gevent", \
     "--workers", "1", \
     "--worker-connections", "50", \
     "--timeout", "3600", \
     "--keep-alive", "65", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "wsgi:app"]
