from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    cfg_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".picobot/config.json").expanduser().resolve()

    if not cfg_path.exists():
        print(f"❌ Missing config: {cfg_path}")
        return 1

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Invalid config JSON: {e}")
        return 1

    tg = cfg.get("telegram", {}) or {}
    enabled = bool(tg.get("enabled", False))
    token = str(tg.get("bot_token", "") or "").strip()

    print(f"telegram.enabled = {enabled}")
    print(f"telegram.bot_token configured = {bool(token and token != 'YOUR_BOT_TOKEN')}")

    if not enabled:
        print("❌ Telegram is disabled in config")
        return 1

    if not token or token == "YOUR_BOT_TOKEN":
        print("❌ Telegram bot token is missing or placeholder")
        return 1

    print("✅ Telegram config looks good")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
