from __future__ import annotations

import json
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from picobot.agent.prompts import detect_language
from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.terminal_tool import TerminalToolBase


class SandboxWebArgs(BaseModel):
    url: str = Field(..., min_length=8)
    timeout_s: float = Field(default=8.0, ge=1.0, le=30.0)
    max_bytes: int = Field(default=200_000, ge=10_000, le=2_000_000)
    whitelist: list[str] = Field(default_factory=list, description="Allowed domains (exact match)")

    # compat: some code used max_chars
    max_chars: int | None = Field(default=None, description="Alias for max_bytes (compat)")


def _cfg_defaults(cfg):
    sw = getattr(getattr(cfg, "sandbox", None), "web", None)
    if not sw:
        return {}
    return {
        "timeout_s": float(getattr(sw, "timeout_s", 8.0) or 8.0),
        "max_bytes": int(getattr(sw, "max_bytes", 200_000) or 200_000),
        "whitelist": list(getattr(sw, "whitelist", []) or []),
    }


def make_sandbox_web_tool(cfg=None):
    runner = TerminalToolBase(allowed_bins=["python"], timeout_s=60, max_output_bytes=250_000)
    defaults = _cfg_defaults(cfg) if cfg is not None else {}

    async def _handler(args: SandboxWebArgs | dict) -> dict:
        try:
            if isinstance(args, dict):
                args = SandboxWebArgs.model_validate(args)

            # apply cfg defaults if caller didn't set
            timeout_s = float(getattr(args, "timeout_s", None) or defaults.get("timeout_s", 8.0))
            max_bytes = int((args.max_chars or 0) or args.max_bytes or defaults.get("max_bytes", 200_000))
            wl = args.whitelist or defaults.get("whitelist", [])

            u = urlparse(args.url)
            if u.scheme not in {"http", "https"}:
                return tool_error("url must be http(s)")
            host = (u.hostname or "").lower().strip()
            if not host:
                return tool_error("invalid url")

            wl_norm = [(d or "").lower().strip() for d in (wl or []) if (d or "").strip()]
            if wl_norm and host not in set(wl_norm):
                return tool_error("domain not allowed")

            payload = json.dumps({"url": args.url, "timeout_s": timeout_s, "max_bytes": max_bytes}, ensure_ascii=False)
            res = runner.run_cmd(
                ["python", "-I", "-c", _PY_FETCH],
                prefix="[sandbox_web]",
                timeout_s=int(timeout_s) + 2,
                input_bytes=payload.encode("utf-8"),
            )
            if res.returncode != 0:
                return tool_error((res.stderr or "error")[:500])

            data = json.loads(res.stdout or "{}")
            if not data.get("ok"):
                return tool_error(data.get("error") or "fetch error")

            text = (data.get("text") or "").strip()
            lang = detect_language(text, default="it") if text else None
            return tool_ok({"url": args.url, "text": text, "length": len(text), "truncated": bool(data.get("truncated"))}, language=lang)
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="sandbox_web",
        description="Fetch a URL via sandbox runner (timeout + size cap + domain whitelist).",
        schema=SandboxWebArgs,
        handler=_handler,
    )


_PY_FETCH = r'''
import sys, json, urllib.request, re
WS = re.compile(r"\s+")

args = json.loads(sys.stdin.read() or "{}")
url = args.get("url") or ""
timeout_s = float(args.get("timeout_s") or 8.0)
max_bytes = int(args.get("max_bytes") or 200000)

req = urllib.request.Request(url, headers={"User-Agent": "picobot-sandbox-web"})
try:
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        raw = r.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    text = raw.decode("utf-8", errors="replace")
    text = WS.sub(" ", text).strip()
    print(json.dumps({"ok": True, "text": text, "truncated": truncated}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
'''
