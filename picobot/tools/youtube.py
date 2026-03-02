from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec


def _call_factory_compat(factory, *args, **kwargs):
    try:
        return factory(*args, **kwargs)
    except TypeError:
        return factory(*args)



_JS_RUNTIME_HINT = (
    "yt-dlp needs a JavaScript runtime to extract YouTube pages. "
    "Install a JS runtime (e.g., node) and/or configure tools.ytdlp_args in your config.json. "
    "Example: \"ytdlp_args\": [\"--js-runtimes\", \"node\"]"
)

def _normalize_ytdlp_bin(binpath: str) -> str:
    """Return an executable path for yt-dlp.
    Accepts either an executable file path or a directory like .../bin.
    """
    if not binpath:
        return "yt-dlp"
    try:
        p = Path(binpath)
    except Exception:
        return binpath
    if p.is_dir():
        # common layouts
        for name in ("yt-dlp", "yt-dlp.exe"):
            cand = p / name
            if cand.exists():
                return str(cand)
    return str(p)


def _js_runtime_hint_if_any(stderr: str) -> str:
    s = (stderr or "").lower()
    if (
        "no supported javascript runtime could be found" in s
        or "youtube extraction without a js runtime has been deprecated" in s
    ):
        # This is often only a WARNING and may still work; do not fail just because of this.
        return _JS_RUNTIME_HINT
    return ""

_YT_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)


def _is_youtube_url(url: str) -> bool:
    return bool(_YT_RX.search(url or ""))


class YTTranscriptArgs(BaseModel):
    url: str = Field(..., min_length=8)
    lang: Optional[str] = Field(default=None, description="Preferred subtitle language, e.g. en, it")


def make_yt_transcript_tool(ytdlp_bin: str, ytdlp_args: list[str] | None = None):
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)

    async def _handler(args: YTTranscriptArgs) -> dict:
        if not _is_youtube_url(args.url):
            raise ValueError("url must be a YouTube URL")

        ytdlp = ytdlp_bin or "yt-dlp"
        extra_args = list(ytdlp_args or [])

        # Default to EN only to avoid unnecessary requests / 429s
        langs = (args.lang or "it.*,it-orig.*,en.*,en-orig.*").strip()

        def run_ytdlp(sub_flag: str):
            cmd = [
                ytdlp,
                *extra_args,
                "--skip-download",
                sub_flag,
                "--sub-format",
                "vtt",
                "--sub-langs",
                langs,
                "-o",
                outtmpl,
                args.url,
            ]
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)

        with tempfile.TemporaryDirectory(prefix="picobot-yt-") as td:
            outtmpl = str(Path(td) / "v.%(ext)s")

            # Try AUTO subs first (often available), then MANUAL subs
            last = run_ytdlp("--write-auto-subs")
            vtts = sorted(Path(td).glob("*.vtt"))

            if not vtts:
                last = run_ytdlp("--write-subs")
                vtts = sorted(Path(td).glob("*.vtt"))

            # Success criterion: we got at least one .vtt (even if yt-dlp had partial errors e.g., 429 for some languages)
            if not vtts:
                hint = _js_runtime_hint_if_any(last.stderr)
                msg = f"yt-dlp did not produce subtitles (.vtt). stderr: {last.stderr.strip()[:600]}"
                if hint:
                    msg = msg + "\n" + hint
                # Add a special note for rate limit
                if "http error 429" in (last.stderr or "").lower() or "too many requests" in (last.stderr or "").lower():
                    msg = msg + "\nRate limit (HTTP 429). Try again later or reduce requested languages."
                raise RuntimeError(msg)

            # Prefer plain 'en' over 'en-orig' when both exist
            prefer_it = (langs.lower().startswith("it") or ".it" in langs.lower())
            
            def score(p: Path) -> tuple:
                n = p.name.lower()
                if prefer_it:
                    if ".it.vtt" in n and "orig" not in n:
                        return (0, n)
                    if "it-orig" in n:
                        return (1, n)
                    if ".en.vtt" in n and "orig" not in n:
                        return (2, n)
                    if "en-orig" in n:
                        return (3, n)
                    return (4, n)
                else:
                    if ".en.vtt" in n and "orig" not in n:
                        return (0, n)
                    if "en-orig" in n:
                        return (1, n)
                    if ".it.vtt" in n and "orig" not in n:
                        return (2, n)
                    if "it-orig" in n:
                        return (3, n)
                    return (4, n)            

            vtts.sort(key=score)
            vtt_text = vtts[0].read_text(encoding="utf-8", errors="ignore")

        # Naive VTT -> text cleanup (good enough for pico)
        lines = []
        for ln in vtt_text.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("WEBVTT") or "-->" in ln:
                continue
            if ln.isdigit():
                continue
            # remove simple tags
            ln = re.sub(r"<[^>]+>", "", ln).strip()
            if ln:
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
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)
    """
    llm_summarize(transcript: str, url: str, lang: Optional[str]) -> str
    """
    async def _handler(args: YTSummaryArgs) -> dict:
        if not _is_youtube_url(args.url):
            raise ValueError("url must be a YouTube URL")

        # reuse transcript tool
        t_tool = _call_factory_compat(make_yt_transcript_tool, ytdlp_bin, ytdlp_args=ytdlp_args)
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
