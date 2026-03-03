from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec
from picobot.tools.terminal_tool import TerminalToolBase


def _call_factory_compat(factory, *args, **kwargs):
    try:
        return factory(*args, **kwargs)
    except TypeError:
        return factory(*args)


_JS_RUNTIME_HINT = (
    "yt-dlp needs a JavaScript runtime to extract YouTube pages. "
    "Install a JS runtime (e.g., node) and/or configure tools.ytdlp_args in your config.json. "
    'Example: "ytdlp_args": ["--js-runtimes", "node"]'
)


def _normalize_ytdlp_bin(binpath: str) -> str:
    if not binpath:
        return "yt-dlp"
    try:
        p = Path(binpath)
    except Exception:
        return binpath
    if p.is_dir():
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
        return _JS_RUNTIME_HINT
    return ""


_YT_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)


def _is_youtube_url(url: str) -> bool:
    return bool(_YT_RX.search(url or ""))


def _lang_from_sub_filename(name: str) -> str:
    n = name.lower()
    m = re.search(r"\.([a-z]{2,3})(?:-orig)?\.(?:vtt|srt)$", n)
    return (m.group(1) if m else "").lower()


def _vtt_or_srt_to_text(raw: str) -> str:
    lines: list[str] = []
    for ln in (raw or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        if t.startswith("WEBVTT"):
            continue
        if "-->" in t:
            continue
        if t.isdigit():
            continue
        t = re.sub(r"<[^>]+>", "", t).strip()
        if t:
            lines.append(t)
    text = " ".join(lines).strip()
    return re.sub(r"\s+", " ", text)


def _ok(data: dict, language: str | None = None) -> dict:
    return {"ok": True, "data": data, "error": None, "language": language}


def _fail(msg: str, language: str | None = None) -> dict:
    return {"ok": False, "data": {}, "error": msg, "language": language}


class YTTranscriptArgs(BaseModel):
    url: str = Field(..., min_length=8)
    lang: Optional[str] = Field(default=None, description="Preferred subtitle language, e.g. en, it")


def make_yt_transcript_tool(ytdlp_bin: str, ytdlp_args: list[str] | None = None):
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)
    extra_args = list(ytdlp_args or [])
    runner = TerminalToolBase(allowed_bins=[ytdlp_bin], cwd=".", timeout_s=180, max_output_bytes=200_000)

    async def _handler(args: YTTranscriptArgs) -> dict:
        if not _is_youtube_url(args.url):
            return _fail("url must be a YouTube URL")

        pref = (args.lang or "").strip().lower()
        if pref:
            langs = f"{pref}.*, {pref}-orig.*"
        else:
            langs = "it.*,it-orig.*,en.*,en-orig.*"
        langs = langs.replace(" ", "")

        def run_ytdlp(out_dir: Path, langs_expr: str):
            cmd = [
                ytdlp_bin,
                *extra_args,
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                langs_expr,
                "--sub-format",
                "vtt/srt/best",
                "--convert-subs",
                "vtt",
                "-P",
                str(out_dir),
                "-o",
                "%(id)s.%(ext)s",
                args.url,
            ]
            # terminal-only logs happen inside TerminalToolBase via stderr
            return runner.run_cmd(cmd, prefix="[yt]")

        with tempfile.TemporaryDirectory(prefix="picobot-yt-") as td:
            out_dir = Path(td)

            tried = []
            for expr in (langs, "it.*,it-orig.*", "en.*,en-orig.*"):
                res = run_ytdlp(out_dir, expr)
                tried.append((expr, res))

                subs = list(out_dir.rglob("*.vtt"))
                if not subs:
                    subs = list(out_dir.rglob("*.srt"))

                if subs:
                    pref_lang = pref or "it"

                    def score(p: Path) -> tuple[int, int, str]:
                        n = p.name.lower()
                        lang = _lang_from_sub_filename(n)
                        want = 0 if lang == pref_lang else 1
                        is_orig = 1 if "orig" in n else 0
                        return (want, is_orig, n)

                    subs.sort(key=score)
                    chosen = subs[0]
                    detected_lang = _lang_from_sub_filename(chosen.name) or (pref or "")
                    raw = chosen.read_text(encoding="utf-8", errors="ignore")
                    text = _vtt_or_srt_to_text(raw)

                    return _ok(
                        {"url": args.url, "language": detected_lang or None, "transcript": text},
                        language=(detected_lang or None),
                    )

            # Failure: no subs at all
            last = tried[-1][1]
            stderr = (last.stderr or "").strip()
            hint = _js_runtime_hint_if_any(stderr)

            msg = f"yt-dlp did not produce subtitles (.vtt/.srt). stderr: {stderr[:600]}"
            if hint:
                msg = msg + "\n" + hint
            low = stderr.lower()
            if "http error 429" in low or "too many requests" in low:
                msg = msg + "\nRate limit (HTTP 429). Try again later or reduce requested languages."

            return _fail(msg)

    return ToolSpec(
        name="yt_transcript",
        description="Fetch YouTube subtitles transcript using yt-dlp (local binary, sandboxed runner).",
        schema=YTTranscriptArgs,
        handler=_handler,
    )


class YTSummaryArgs(BaseModel):
    url: str = Field(..., min_length=8)
    lang: Optional[str] = Field(default=None, description="Preferred subtitle language, e.g. en, it")


def make_yt_summary_tool(ytdlp_bin: str, llm_summarize, ytdlp_args: list[str] | None = None):
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)

    async def _handler(args: YTSummaryArgs) -> dict:
        if not _is_youtube_url(args.url):
            return _fail("url must be a YouTube URL")

        t_tool = _call_factory_compat(make_yt_transcript_tool, ytdlp_bin, ytdlp_args=ytdlp_args)
        t_res = await t_tool.handler(t_tool.schema.model_validate({"url": args.url, "lang": args.lang}))
        if not t_res.get("ok"):
            return t_res

        data = t_res.get("data") or {}
        transcript = (data.get("transcript") or "").strip()
        transcript_lang = (data.get("language") or args.lang or None)

        summary = await llm_summarize(transcript=transcript, url=args.url, lang=transcript_lang)
        return _ok(
            {
                "url": args.url,
                "summary": summary,
                "language": transcript_lang,
                "transcript_chars": len(transcript),
            },
            language=transcript_lang,
        )

    return ToolSpec(
        name="yt_summary",
        description="Summarize a YouTube video by fetching transcript via yt-dlp then summarizing with local LLM.",
        schema=YTSummaryArgs,
        handler=_handler,
    )
