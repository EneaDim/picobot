from __future__ import annotations

import re
import urllib.request
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from picobot.agent.prompts import detect_language
from picobot.tools.base import ToolSpec, tool_error, tool_ok


_WS_RX = re.compile(r"\s+")


class SandboxWebArgs(BaseModel):
    url: str = Field(..., min_length=8)
    timeout_s: float = Field(default=8.0, ge=1.0, le=30.0)
    max_bytes: int = Field(default=200_000, ge=10_000, le=2_000_000)
    whitelist: list[str] = Field(default_factory=list, description="Allowed domains (exact match)")


def make_sandbox_web_tool():
    async def _handler(args: SandboxWebArgs) -> dict:
        try:
            u = urlparse(args.url)
            if u.scheme not in {"http", "https"}:
                return tool_error("url must be http(s)")

            host = (u.hostname or "").lower().strip()
            if not host:
                return tool_error("invalid url")

            wl = [(d or "").lower().strip() for d in (args.whitelist or []) if (d or "").strip()]
            if wl and host not in set(wl):
                return tool_error("domain not allowed")

            req = urllib.request.Request(
                args.url,
                headers={"User-Agent": "picobot-sandbox-web"},
            )
            with urllib.request.urlopen(req, timeout=float(args.timeout_s)) as r:
                raw = r.read(int(args.max_bytes) + 1)
                if len(raw) > int(args.max_bytes):
                    return tool_error("response too large")
                text = raw.decode("utf-8", errors="replace")

            text = _WS_RX.sub(" ", text).strip()
            lang = detect_language(text, default="it") if text else None
            return tool_ok({"url": args.url, "text": text}, language=lang)
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="sandbox_web",
        description="Fetch a URL in a sandbox (timeout + size cap + domain whitelist).",
        schema=SandboxWebArgs,
        handler=_handler,
    )
