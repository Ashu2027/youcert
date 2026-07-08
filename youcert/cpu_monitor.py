"""
==============================================================================
YOUCERT cpu_monitor.py - CPU-Based Auto-Scale Trigger
==============================================================================

Monitors container CPU usage in a background greenlet.
When sustained CPU usage exceeds a threshold (default 90%), the container
signals to Cloudflare's Load Balancer that it is "overloaded" by rejecting
new incoming requests with a 503 response.

Cloudflare will then spin up a fresh container automatically to handle
the overflow, providing true CPU-based horizontal auto-scaling.

DESIGN:
  - One background greenlet sleeps and samples psutil every CHECK_INTERVAL.
  - A rolling window of samples (WINDOW_SIZE) is kept to prevent false triggers.
  - If the AVERAGE of recent samples exceeds CPU_THRESHOLD, `_overloaded` is set.
  - A Flask before_request hook checks this flag and returns 503 instantly for
    any non-health check route.
==============================================================================
"""

import time
import threading
import logging

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
CPU_THRESHOLD    = 90.0  # Reject new requests if avg CPU % exceeds this
CHECK_INTERVAL   = 5     # Seconds between CPU samples
WINDOW_SIZE      = 3     # Number of samples to average (3 × 5s = 15s window)
COOLDOWN_CHECKS  = 3     # How many clean samples before accepting requests again

# ── State ──────────────────────────────────────────────────────────────────────
_overloaded     = False   # Flag read by Flask before_request hook
_monitor_started = False  # Guard against double-start
_samples: list  = []      # Rolling window of CPU samples
_cooldown       = 0       # Clean checks remaining to exit overload state


def _monitor_loop():
    """Background loop that samples CPU and sets the _overloaded flag."""
    global _overloaded, _samples, _cooldown

    try:
        import psutil
    except ImportError:
        logger.warning("[cpu_monitor] psutil not installed — CPU auto-scaling disabled.")
        return

    logger.info(
        f"[cpu_monitor] Started — threshold={CPU_THRESHOLD}%, "
        f"interval={CHECK_INTERVAL}s, window={WINDOW_SIZE} samples"
    )

    # Warm-up: call once first so the first real reading is accurate
    psutil.cpu_percent(interval=None)
    time.sleep(CHECK_INTERVAL)

    while True:
        try:
            sample = psutil.cpu_percent(interval=None)
            _samples.append(sample)

            # Keep only the last WINDOW_SIZE samples
            if len(_samples) > WINDOW_SIZE:
                _samples.pop(0)

            avg_cpu = sum(_samples) / len(_samples)

            if not _overloaded:
                if len(_samples) == WINDOW_SIZE and avg_cpu >= CPU_THRESHOLD:
                    _overloaded = True
                    _cooldown = COOLDOWN_CHECKS
                    logger.warning(
                        f"[cpu_monitor] OVERLOADED — avg CPU {avg_cpu:.1f}% >= {CPU_THRESHOLD}%. "
                        f"Rejecting new requests to trigger Cloudflare scale-out."
                    )
            else:
                # Currently overloaded — check if CPU has cooled down
                if avg_cpu < CPU_THRESHOLD:
                    _cooldown -= 1
                    if _cooldown <= 0:
                        _overloaded = False
                        logger.info(
                            f"[cpu_monitor] RECOVERED — avg CPU {avg_cpu:.1f}% < {CPU_THRESHOLD}%. "
                            f"Accepting requests again."
                        )
                else:
                    # Still hot, reset the cooldown counter
                    _cooldown = COOLDOWN_CHECKS

        except Exception as exc:
            logger.error(f"[cpu_monitor] Sample error: {exc}")

        time.sleep(CHECK_INTERVAL)


def start_monitor():
    """
    Start the CPU monitor background thread.
    Safe to call multiple times — starts only once per process.
    Uses a daemon thread so it auto-exits when the main process exits.
    """
    global _monitor_started
    if _monitor_started:
        return

    _monitor_started = True
    thread = threading.Thread(target=_monitor_loop, name="cpu_monitor", daemon=True)
    thread.start()
    logger.info("[cpu_monitor] Background thread launched.")


def is_overloaded() -> bool:
    """Return True if the container's CPU is currently saturated."""
    return _overloaded
