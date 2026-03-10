from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from picobot.prompts import detect_language
from picobot.runtime_config import cfg_get
from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.terminal_tool import TerminalToolBase


class WebToolArgs(BaseModel):
    url: str = Field(..., min_length=8)
    timeout_s: float = Field(default=8.0, ge=1.0, le=30.0)
    max_bytes: int = Field(default=200_000, ge=10_000, le=2_000_000)
    whitelist: list[str] = Field(default_factory=list)
    max_chars: int | None = Field(default=None)


def _cfg_value(cfg: Any | None, path: str, default: Any) -> Any:
    if cfg is not None:
        current = cfg
        for part in path.split("."):
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                return cfg_get(path, default)
        return current
    return cfg_get(path, default)


def make_web_tool(cfg=None):
    allowed_bins = list(_cfg_value(cfg, "sandbox.exec.allowed_bins", ["python"]) or ["python"])
    default_timeout = float(_cfg_value(cfg, "sandbox.web.timeout_s", 10.0) or 10.0)
    default_max_bytes = int(_cfg_value(cfg, "sandbox.web.max_bytes", 200_000) or 200_000)
    default_whitelist = list(_cfg_value(cfg, "sandbox.web.whitelist_domains", []) or [])

    runner = TerminalToolBase(
        cfg=cfg,
        allowed_bins=allowed_bins,
        timeout_s=int(max(default_timeout, 1.0)),
        max_output_bytes=int(_cfg_value(cfg, "sandbox.exec.max_output_bytes", 200_000) or 200_000),
    )

    async def _handler(args: WebToolArgs | dict) -> dict:
        try:
            if isinstance(args, dict):
                args = WebToolArgs.model_validate(args)

            timeout_s = float(getattr(args, "timeout_s", None) or default_timeout)
            max_bytes = int((args.max_chars or 0) or args.max_bytes or default_max_bytes)
            wl = args.whitelist or default_whitelist

            u = urlparse(args.url)
            if u.scheme not in {"http", "https"}:
                return tool_error("url must be http(s)")

            host = (u.hostname or "").lower().strip()
            if not host:
                return tool_error("invalid url")

            wl_norm = [(d or "").lower().strip() for d in (wl or []) if (d or "").strip()]
            if wl_norm and host not in set(wl_norm):
                return tool_error("domain not allowed")

            payload = json.dumps(
                {
                    "url": args.url,
                    "timeout_s": timeout_s,
                    "max_bytes": max_bytes,
                },
                ensure_ascii=False,
            )

            res = runner.run_cmd(
                ["python", "-I", "-c", _PY_FETCH],
                prefix="[web]",
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

            return tool_ok(
                {
                    "backend": runner.backend,
                    "url": args.url,
                    "title": (data.get("title") or "").strip(),
                    "description": (data.get("description") or "").strip(),
                    "text": text,
                    "length": len(text),
                    "truncated": bool(data.get("truncated")),
                },
                language=lang,
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="web",
        description="Fetch a URL inside the configured sandbox backend.",
        schema=WebToolArgs,
        handler=_handler,
    )


_PY_FETCH = r'''
import sys, json, urllib.request, re, html as html_lib

args = json.loads(sys.stdin.read() or "{}")
url = args.get("url") or ""
timeout_s = float(args.get("timeout_s") or 8.0)
max_bytes = int(args.get("max_bytes") or 200000)

req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    },
)

def _meta(rx, html):
    m = re.search(rx, html, flags=re.I | re.S)
    if not m:
        return ""
    return html_lib.unescape(m.group(1)).strip()

def _clean_title(s):
    s = html_lib.unescape(s or "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*[|\-–—·»›]+\s*.*$", "", s).strip()
    return s

def _clean_text(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<svg.*?</svg>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<noscript.*?</noscript>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<header.*?</header>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<footer.*?</footer>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<nav.*?</nav>", " ", html, flags=re.I | re.S)

    html = re.sub(r"<[^>]+>", " ", html)
    text = html_lib.unescape(html)
    text = re.sub(r"\b(?:Skip to main content|Passa ai contenuti principali|Accedi direttamente.*?|Cookie.*?|Privacy.*?|Terms.*?|Newsletter.*?)\b", " ", text, flags=re.I)
    text = re.sub(r'"@context"\s*:\s*"https://schema.org/.*?(?=[\.\!\?])', " ", text, flags=re.I | re.S)
    text = re.sub(r"\s+", " ", text).strip()

    parts = re.split(r'(?<=[\.\!\?])\s+', text)
    kept = []
    for p in parts:
        p = p.strip()
        if len(p) < 40:
            continue
        low = p.lower()
        if "schema.org" in low or "javascript" in low:
            continue
        if "<a href" in low or "{" in p or "}" in p:
            continue
        if "seleziona la tua lingua" in low or "cambia la lingua" in low:
            continue
        kept.append(p)
        if len(" ".join(kept)) > 1800:
            break
    return " ".join(kept).strip()

try:
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        raw = r.read(max_bytes + 1)

    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]

    html = raw.decode("utf-8", errors="replace")

    title = _meta(r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"'](.*?)[\"']", html)
    if not title:
        title = _meta(r"<title>(.*?)</title>", html)
    title = _clean_title(title)

    description = _meta(r"<meta[^>]+property=[\"']og:description[\"'][^>]+content=[\"'](.*?)[\"']", html)
    if not description:
        description = _meta(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"']", html)
    description = re.sub(r"\s+", " ", description).strip()

    text = _clean_text(html)

    print(json.dumps({
        "ok": True,
        "title": title,
        "description": description,
        "text": text,
        "truncated": truncated
    }, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
'''
