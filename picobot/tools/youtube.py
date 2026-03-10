from __future__ import annotations


import os

import json
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

DEBUG_DOCKER = os.getenv("PICOBOT_DEBUG_CLI", "0").strip().lower() in {"1", "true", "yes", "on"}


def _debug_docker(msg: str) -> None:
    if DEBUG_DOCKER:
        print(f"[debug][docker] {msg}")

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


def _extract_transcript_with_ytdlp_cmd(url: str, prefer_sub_langs: list[str]) -> list[str]:
    langs = ",".join([x.strip() for x in prefer_sub_langs if str(x).strip()]) or "it,en.*"
    return [
        "--skip-download",
        "--write-auto-sub",
        "--write-sub",
        "--sub-lang", langs,
        "--sub-format", "vtt",
        "--print", "after_move:subtitle:%(filepath)s",
        url,
    ]


def _clean_ytdlp_error(text: str) -> str:
    raw = (text or "").strip()
    if "HTTP Error 429" in raw or "Too Many Requests" in raw:
        return (
            "YouTube sta limitando temporaneamente il download dei sottotitoli/transcript (HTTP 429 Too Many Requests). "
            "Riprova più tardi oppure cambia video."
        )
    if raw:
        return raw
    return "yt-dlp failed"


def make_yt_transcript_tool(ytdlp_bin: str, ytdlp_args: list[str] | None = None):
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)
    extra_args = list(ytdlp_args or [])

    runner = TerminalToolBase(
        allowed_bins=[ytdlp_bin],
        timeout_s=180,
        max_output_bytes=200_000,
    )

    async def _handler(args: YTTranscriptArgs) -> dict:
        try:
            cmd = [ytdlp_bin, *extra_args, *_extract_transcript_with_ytdlp_cmd(args.url, args.prefer_sub_langs)]
            res = runner.run_cmd(
                cmd,
                prefix="[youtube:transcript]",
                timeout_s=int(args.timeout_s),
            )

            if res.returncode != 0:
                return tool_error(_clean_ytdlp_error((res.stderr or "") + "\n" + (res.stdout or ""))[:2000])

            lines = [line.strip() for line in (res.stdout or "").splitlines() if line.strip()]
            subtitle_paths = [line for line in lines if line.endswith(".vtt") or line.endswith(".srv3") or line.endswith(".ttml")]

            return tool_ok(
                {
                    "url": args.url,
                    "subtitle_paths": subtitle_paths,
                    "stdout": (res.stdout or "")[:4000],
                    "stderr": (res.stderr or "")[:4000],
                    "backend": runner.backend,
                },
                language=args.lang,
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="yt_transcript",
        description="Extract YouTube transcript/subtitles using yt-dlp.",
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
        allowed_bins=[ytdlp_bin, "python"],
        timeout_s=180,
        max_output_bytes=250_000,
    )

    async def _handler(args: YTSummaryArgs) -> dict:
        try:
            cmd = [ytdlp_bin, *extra_args, *_extract_transcript_with_ytdlp_cmd(args.url, args.prefer_sub_langs)]
            res = runner.run_cmd(
                cmd,
                prefix="[youtube:summary]",
                timeout_s=int(args.timeout_s),
            )

            if res.returncode != 0:
                return tool_error(_clean_ytdlp_error((res.stderr or "") + "\n" + (res.stdout or ""))[:2000])

            lines = [line.strip() for line in (res.stdout or "").splitlines() if line.strip()]
            subtitle_paths = [line for line in lines if line.endswith(".vtt") or line.endswith(".srv3") or line.endswith(".ttml")]

            transcript = ""
            if subtitle_paths:
                path = subtitle_paths[-1]
                read_res = runner.run_cmd(
                    ["python", "-I", "-c", _PY_READ_TEXT, path],
                    prefix="[youtube:summary:read]",
                    timeout_s=10,
                )
                if read_res.returncode == 0:
                    payload = json.loads(read_res.stdout or "{}")
                    transcript = str(payload.get("text") or "").strip()

            if not transcript:
                transcript = (res.stdout or "").strip()

            if not transcript:
                return tool_error("no transcript available")

            summary = await llm_summarize(transcript, args.url, args.lang)

            return tool_ok(
                {
                    "url": args.url,
                    "summary": (summary or "").strip(),
                    "transcript_preview": transcript[:4000],
                    "subtitle_paths": subtitle_paths,
                    "backend": runner.backend,
                },
                language=args.lang,
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="yt_summary",
        description="Summarize a YouTube video transcript using yt-dlp plus the local LLM.",
        schema=YTSummaryArgs,
        handler=_handler,
    )


_PY_READ_TEXT = r'''
import json
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser().resolve()
try:
    text = path.read_text(encoding="utf-8", errors="replace")
    print(json.dumps({"ok": True, "text": text}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
'''
