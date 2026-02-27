from __future__ import annotations

import os

DEBUG = os.environ.get("PICOBOT_TEST_DEBUG", "").strip() in {"1", "true", "yes", "on"}

def dbg(*args):
    """Print debug info only if PICOBOT_TEST_DEBUG=1 (or if running pytest -s)."""
    if DEBUG:
        print(*args)
