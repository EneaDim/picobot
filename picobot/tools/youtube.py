from __future__ import annotations

import json
import os
import shlex
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.paths import resolve_repo_path
from picobot.tools.terminal_tool import TerminalToolBase

LLMSummarize = Callable[[str, str, str | None], Awaitable[str]]

DEBUG_YT = os.getenv("PICOBOT_DEBUG_CLI", "0").strip().lower() in {"1", "true", "yes", "on"}


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
            "YouTube sta limitando temporaneamente il download dei sottotitoli (HTTP 429 Too Many Requests). "
            "Il comando tollera errori parziali, ma alcune lingue richieste potrebbero non essere disponibili."
        )
    if raw:
        return raw
    return "yt-dlp failed"


def _quoted(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def _langs_list(prefer_sub_langs: list[str]) -> list[str]:
    langs = [str(x).strip() for x in (prefer_sub_langs or []) if str(x).strip()]
    return langs if langs else ["it", "it-orig", "it-IT"]


def _langs_value(prefer_sub_langs: list[str]) -> str:
    return ",".join(_langs_list(prefer_sub_langs))


def _build_pipeline_script(
    ytdlp_bin: str,
    extra_args: list[str],
    url: str,
    prefer_sub_langs: list[str],
) -> str:
    langs = _langs_list(prefer_sub_langs)
    langs_csv = ",".join(langs)

    cmd = [
        ytdlp_bin,
        *extra_args,
        "--ignore-errors",
        "--skip-download",
        "--write-auto-subs",
        "--sub-langs",
        langs_csv,
        "--convert-subs",
        "vtt",
        "-o",
        "%(id)s.%(ext)s",
        url,
    ]
    ytdlp_cmd = _quoted(cmd)

    lang_json = json.dumps(langs)

    script = f"""
set -euo pipefail

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
cd "$workdir"

{ytdlp_cmd} 1>&2 || true

shopt -s nullglob
files=( *.vtt )
if [ "${{#files[@]}}" -eq 0 ]; then
  echo '{{"ok":false,"error":"no vtt subtitles produced"}}'
  exit 0
fi

python3 - <<'PYEOF'
import json
import re
from pathlib import Path

files = sorted(Path(".").glob("*.vtt"))
if not files:
    print(json.dumps({{"ok": False, "error": "no vtt subtitles produced"}}, ensure_ascii=False))
    raise SystemExit(0)

preferred_langs = {lang_json}

def score_file(path_str: str):
    name = Path(path_str).name.lower()
    for idx, lang in enumerate(preferred_langs):
        token = f".{{lang.lower()}}.".format(lang=lang)
        if token in name:
            return (0, idx, len(name))
    return (1, 999, len(name))

selected = sorted((str(p) for p in files), key=score_file)[0]
selected_path = Path(selected)

timestamp_re = re.compile(
    r"^\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{3}}\\s+-->\\s+\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{3}}"
)
tag_re = re.compile(r"<[^>]+>")

parts: list[str] = []

text = selected_path.read_text(encoding="utf-8", errors="replace")
for raw_line in text.splitlines():
    line = raw_line.strip()

    if (
        not line
        or line == "WEBVTT"
        or line.startswith("NOTE")
        or line.startswith("Kind:")
        or line.startswith("Language:")
        or line.isdigit()
        or timestamp_re.match(line)
    ):
        continue

    line = tag_re.sub("", line)
    line = (
        line.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .strip()
    )
    if not line:
        continue

    if parts and parts[-1] == line:
        continue
    parts.append(line)

transcript = re.sub(r"\\s+", " ", " ".join(parts)).strip()

if not transcript:
    print(json.dumps({{"ok": False, "error": "empty transcript"}}, ensure_ascii=False))
    raise SystemExit(0)

print(json.dumps(
    {{
        "ok": True,
        "transcript": transcript,
        "transcript_preview": transcript[:4000],
        "subtitle_paths": [str(p.name) for p in files],
        "selected_subtitle_path": selected_path.name,
        "preferred_langs": preferred_langs,
    }},
    ensure_ascii=False
))
PYEOF
""".strip()

    return script


def make_yt_transcript_tool(
    ytdlp_bin: str,
    ytdlp_args: list[str] | None = None,
    cfg: Any | None = None,
):
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)
    extra_args = list(ytdlp_args or [])

    runner = TerminalToolBase(
        allowed_bins=["bash"],
        cfg=cfg,
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

            _debug_yt(f"transcript backend={runner.backend}")
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
                return tool_error(_clean_ytdlp_error((res.stderr or "") + "\\n" + (res.stdout or ""))[:4000])

            payload = json.loads((res.stdout or "").strip() or "{}")
            if not payload.get("ok"):
                return tool_error(str(payload.get("error") or "youtube transcript failed"))

            return tool_ok(
                {
                    "url": args.url,
                    "transcript": str(payload.get("transcript") or "").strip(),
                    "transcript_preview": str(payload.get("transcript_preview") or "").strip(),
                    "subtitle_paths": list(payload.get("subtitle_paths") or []),
                    "selected_subtitle_path": str(payload.get("selected_subtitle_path") or "").strip(),
                    "preferred_langs": list(payload.get("preferred_langs") or []),
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
        description="Extract raw YouTube transcript text using yt-dlp and parse one preferred VTT subtitle track without timing.",
        schema=YTTranscriptArgs,
        handler=_handler,
    )


def make_yt_summary_tool(
    ytdlp_bin: str,
    llm_summarize: LLMSummarize,
    ytdlp_args: list[str] | None = None,
    cfg: Any | None = None,
):
    ytdlp_bin = _normalize_ytdlp_bin(ytdlp_bin)
    extra_args = list(ytdlp_args or [])

    runner = TerminalToolBase(
        allowed_bins=["bash"],
        cfg=cfg,
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

            _debug_yt(f"summary backend={runner.backend}")
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
                return tool_error(_clean_ytdlp_error((res.stderr or "") + "\\n" + (res.stdout or ""))[:4000])

            payload = json.loads((res.stdout or "").strip() or "{}")
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
                    "selected_subtitle_path": str(payload.get("selected_subtitle_path") or "").strip(),
                    "preferred_langs": list(payload.get("preferred_langs") or []),
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
        description="Summarize a YouTube video using raw subtitle text extracted from the best matching preferred VTT track.",
        schema=YTSummaryArgs,
        handler=_handler,
    )
