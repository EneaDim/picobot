from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec


_YT_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)


def _is_youtube_url(url: str) -> bool:
    return bool(_YT_RX.search(url or ""))


class YTTranscriptArgs(BaseModel):
    url: str = Field(..., min_length=8)
    lang: Optional[str] = Field(default=None, description="Preferred subtitle language, e.g. en, it")


def make_yt_transcript_tool(ytdlp_bin: str, ytdlp_args: list[str] | None = None):
    async def _handler(args: YTTranscriptArgs) -> dict:
        if not _is_youtube_url(args.url):
            raise ValueError("url must be a YouTube URL")

        ytdlp = ytdlp_bin or "yt-dlp"

        with tempfile.TemporaryDirectory(prefix="picobot-yt-") as td:
            outtmpl = str(Path(td) / "v.%(ext)s")

            # Try subtitles first (manual or auto). We avoid downloading video by using --skip-download.
            cmd = [
                ytdlp,
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-format", "vtt",
                "--sub-langs", (args.lang or "en.*,it.*").strip(),
                "-o", outtmpl,
                args.url,
            ]

            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
            if p.returncode != 0:
                raise RuntimeError(f"yt-dlp failed: {p.stderr.strip()[:400]}")

            # Find any .vtt
            vtts = list(Path(td).glob("*.vtt"))
            if not vtts:
                # fallback: ask yt-dlp for metadata; at least return title
                raise RuntimeError("No subtitles found for this video (no .vtt).")

            # Read first vtt found (best-effort)
            vtt = vtts[0].read_text(encoding="utf-8", errors="ignore")

        # Naive VTT -> text cleanup (good enough for pico)
        lines = []
        for ln in vtt.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("WEBVTT") or "-->" in ln:
                continue
            # drop numeric cues
            if ln.isdigit():
                continue
            lines.append(ln)
        text = " ".join(lines).strip()
        text = re.sub(r"\s+", " ", text)

        return {"url": args.url, "lang": args.lang, "transcript": text}

    return ToolSpec(
        name="yt_transcript",
        description="Fetch YouTube subtitles transcript using yt-dlp (local binary).",
        schema=YTTranscriptArgs,
        handler=_handler,
    )


class YTSummaryArgs(BaseModel):
    url: str = Field(..., min_length=8)
    lang: Optional[str] = Field(default=None, description="Output language preference, e.g. en, it")


def make_yt_summary_tool(ytdlp_bin: str, llm_summarize, ytdlp_args: list[str] | None = None):
    """
    llm_summarize(transcript: str, url: str, lang: Optional[str]) -> str
    """
    async def _handler(args: YTSummaryArgs) -> dict:
        if not _is_youtube_url(args.url):
            raise ValueError("url must be a YouTube URL")

        # reuse transcript tool
        t_tool = make_yt_transcript_tool(ytdlp_bin)
        t = await t_tool.handler(t_tool.schema.model_validate({"url": args.url, "lang": args.lang}))
        transcript = t["transcript"]
        summary = await llm_summarize(transcript=transcript, url=args.url, lang=args.lang)
        return {"url": args.url, "summary": summary, "transcript_chars": len(transcript)}

    return ToolSpec(
        name="yt_summary",
        description="Summarize a YouTube video by fetching transcript via yt-dlp then summarizing with local LLM.",
        schema=YTSummaryArgs,
        handler=_handler,
    )
