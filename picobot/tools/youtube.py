from __future__ import annotations

import json
import os
import shlex
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.paths import resolve_repo_path
from picobot.tools.terminal_tool import TerminalToolBase

LLMSummarize = Callable[[str, str, str | None], Awaitable[str]]


class YTTranscriptArgs(BaseModel):
    url: str = Field(..., min_length=8)
    lang: str | None = Field(default=None)
    prefer_sub_langs: list[str] = Field(default_factory=list)
    timeout_s: int = Field(default=180, ge=5, le=1200)


class YTSummaryArgs(BaseModel):
    url: str = Field(..., min_length=8)
    lang: str | None = Field(default=None)
    prefer_sub_langs: list[str] = Field(default_factory=list)
    timeout_s: int = Field(default=180, ge=5, le=1200)


DEBUG_YT = os.getenv("PICOBOT_DEBUG_CLI", "0").strip().lower() in {"1", "true", "yes", "on"}


def _debug_yt(msg: str) -> None:
    if DEBUG_YT:
        print(f"[debug][youtube] {msg}")


def _normalize_ytdlp_bin(ytdlp_bin: str) -> str:
    value = str(ytdlp_bin or "").strip()
    if not value:
        return "yt-dlp"
    if "/" not in value and "\\" not in value and not value.startswith("."):
        return value
    return resolve_repo_path(value)


def _clean_ytdlp_error(text: str) -> str:
    raw = (text or "").strip()
    if "HTTP Error 429" in raw or "Too Many Requests" in raw:
        return (
            "YouTube sta limitando temporaneamente il transcript download (HTTP 429 Too Many Requests). "
            "Allinea cookies / user-agent / pacing del comando yt-dlp."
        )
    if raw:
        return raw
    return "yt-dlp failed"


def _quoted(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def _langs_value(prefer_sub_langs: list[str]) -> str:
    langs = [str(x).strip() for x in (prefer_sub_langs or []) if str(x).strip()]
    return ",".join(langs) if langs else "en"


def _build_pipeline_script(ytdlp_bin: str, extra_args: list[str], url: str, prefer_sub_langs: list[str]) -> str:
    langs = _langs_value(prefer_sub_langs)

    cmd = [
        ytdlp_bin,
        *extra_args,
        "--skip-download",
        "--write-auto-subs",
        "--write-subs",
        "--sub-lang", langs,
        "--sub-format", "json3",
        "-o", "%(id)s.%(ext)s",
        url,
    ]
    ytdlp_cmd = _quoted(cmd)

    # Pipeline:
    # 1. scarica json3
    # 2. estrae testo dagli events
    # 3. elimina righe vuote e duplicati adiacenti/logici
    # 4. concatena tutto in una riga transcript.txt
    script = f"""
set -euo pipefail

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
cd "$workdir"

{ytdlp_cmd} 1>&2

shopt -s nullglob
files=( *.json3 )
if [ "${{#files[@]}}" -eq 0 ]; then
  echo '{{"ok":false,"error":"no json3 subtitles produced"}}'
  exit 0
fi

jq -r '.events[] | select(.segs) | [.segs[]?.utf8] | join("")' -- *.json3 \\
  | awk 'NF && !seen[$0]++' \\
  | paste -sd" " - > transcript.txt

if [ ! -s transcript.txt ]; then
  echo '{{"ok":false,"error":"empty transcript"}}'
  exit 0
fi

python - <<'PYEOF'
import json
from pathlib import Path

text = Path("transcript.txt").read_text(encoding="utf-8", errors="replace").strip()
files = sorted(str(p.name) for p in Path(".").glob("*.json3"))

print(json.dumps({{
    "ok": True,
    "transcript": text,
    "transcript_preview": text[:4000],
    "subtitle_paths": files,
}}, ensure_ascii=False))
PYEOF
""".strip()

    return script


def make_yt_transcript_tool(ytdlp_bin: str, ytdlp_args: list[str] | None = None):
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)
    extra_args = list(ytdlp_args or [])

    runner = TerminalToolBase(
        allowed_bins=["bash"],
        timeout_s=180,
        max_output_bytes=250_000,
    )

    async def _handler(args: YTTranscriptArgs) -> dict:
        try:
            script = _build_pipeline_script(
                ytdlp_bin=ytdlp_bin,
                extra_args=extra_args,
                url=args.url,
                prefer_sub_langs=args.prefer_sub_langs,
            )

            _debug_yt(f"transcript ytdlp_bin={ytdlp_bin}")
            _debug_yt(f"transcript extra_args={extra_args}")
            _debug_yt("transcript shell script follows:")
            _debug_yt(script)

            res = runner.run_cmd(
                ["bash", "-lc", script],
                prefix="[youtube:transcript]",
                timeout_s=int(args.timeout_s),
            )

            if res.returncode != 0:
                return tool_error(_clean_ytdlp_error((res.stderr or "") + "\n" + (res.stdout or ""))[:4000])

            payload = json.loads(res.stdout or "{}")
            if not payload.get("ok"):
                return tool_error(str(payload.get("error") or "youtube transcript failed"))

            return tool_ok(
                {
                    "url": args.url,
                    "transcript": str(payload.get("transcript") or "").strip(),
                    "transcript_preview": str(payload.get("transcript_preview") or "").strip(),
                    "subtitle_paths": list(payload.get("subtitle_paths") or []),
                    "backend": runner.backend,
                    "ytdlp_bin": ytdlp_bin,
                    "extra_args": extra_args,
                },
                language=args.lang,
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="yt_transcript",
        description="Extract YouTube transcript/subtitles using yt-dlp + jq pipeline.",
        schema=YTTranscriptArgs,
        handler=_handler,
    )


def make_yt_summary_tool(
    ytdlp_bin: str,
    llm_summarize: LLMSummarize,
    ytdlp_args: list[str] | None = None,
):
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)
    extra_args = list(ytdlp_args or [])

    runner = TerminalToolBase(
        allowed_bins=["bash"],
        timeout_s=180,
        max_output_bytes=300_000,
    )

    async def _handler(args: YTSummaryArgs) -> dict:
        try:
            script = _build_pipeline_script(
                ytdlp_bin=ytdlp_bin,
                extra_args=extra_args,
                url=args.url,
                prefer_sub_langs=args.prefer_sub_langs,
            )

            _debug_yt(f"summary ytdlp_bin={ytdlp_bin}")
            _debug_yt(f"summary extra_args={extra_args}")
            _debug_yt("summary shell script follows:")
            _debug_yt(script)

            res = runner.run_cmd(
                ["bash", "-lc", script],
                prefix="[youtube:summary]",
                timeout_s=int(args.timeout_s),
            )

            if res.returncode != 0:
                return tool_error(_clean_ytdlp_error((res.stderr or "") + "\n" + (res.stdout or ""))[:4000])

            payload = json.loads(res.stdout or "{}")
            if not payload.get("ok"):
                return tool_error(str(payload.get("error") or "youtube summary failed"))

            transcript = str(payload.get("transcript") or "").strip()
            if not transcript:
                return tool_error("no transcript available")

            summary = await llm_summarize(transcript, args.url, args.lang)

            return tool_ok(
                {
                    "url": args.url,
                    "summary": (summary or "").strip(),
                    "transcript_preview": str(payload.get("transcript_preview") or "").strip(),
                    "subtitle_paths": list(payload.get("subtitle_paths") or []),
                    "backend": runner.backend,
                    "ytdlp_bin": ytdlp_bin,
                    "extra_args": extra_args,
                },
                language=args.lang,
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="yt_summary",
        description="Summarize a YouTube video transcript using yt-dlp + jq pipeline + LLM.",
        schema=YTSummaryArgs,
        handler=_handler,
    )
