from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional, Tuple

from picobot.agent.prompts import detect_language, podcast_system_prompt, podcast_user_prompt

StatusCb = Callable[[str], Awaitable[None]]


def _pod_dbg(cfg, msg: str) -> None:
    try:
        if (
            getattr(getattr(cfg, "telegram", None), "debug_terminal", False)
            or getattr(getattr(cfg, "debug", None), "enabled", False)
        ):
            print(f"[podcast] {msg}", file=sys.stderr)
    except Exception:
        pass


def _slug(s: str, max_len: int = 48) -> str:
    t = (s or "").strip().lower()
    t = re.sub(r"\s+", "-", t)
    t = re.sub(r"[^a-z0-9\-_]+", "", t)
    t = t.strip("-_")
    if not t:
        t = "podcast"
    return t[: max(12, int(max_len))]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------
# Trigger (NO LLM): config-driven + permissive "podcast ..." fallback
# ---------------------------------------------------------

_EN_FALLBACK = ["podcast", "podcast about", "make a podcast", "build a podcast", "generate a podcast"]
_IT_FALLBACK = ["podcast", "podcast su", "crea un podcast", "fammi un podcast", "genera un podcast", "fai un podcast"]


def detect_podcast_request(text: str, cfg) -> Optional[Tuple[str, str]]:
    t = (text or "").strip()
    if not t:
        return None

    pcfg = getattr(cfg, "podcast", None)
    if not pcfg or not getattr(pcfg, "enabled", False):
        return None

    default_lang = getattr(cfg, "default_language", "it")
    lang = detect_language(t, default=default_lang)
    low = t.lower()

    triggers = getattr(pcfg, "triggers", None)
    trig_list: list[str] = []
    if triggers:
        try:
            trig_list = list(getattr(triggers, lang) or [])
        except Exception:
            trig_list = []

    # Always include safe fallbacks (still deterministic, no LLM)
    if (lang or "").lower().startswith("it"):
        trig_list = [*(trig_list or []), *_IT_FALLBACK]
    else:
        trig_list = [*(trig_list or []), *_EN_FALLBACK]

    for trig in trig_list:
        trig_low = (trig or "").strip().lower()
        if not trig_low:
            continue

        if low.startswith(trig_low):
            topic = t[len(trig) :].strip(" \t\n\r:,-")
            return (topic or "podcast", lang)

    # extra permissive: any message starting with "podcast" triggers
    if low.startswith("podcast"):
        topic = t[len("podcast") :].strip(" \t\n\r:,-")
        return (topic or "podcast", lang)

    return None


# ---------------------------------------------------------
# Output
# ---------------------------------------------------------


@dataclass(frozen=True)
class PodcastResult:
    audio_path: str
    script: str
    run_dir: str


# ---------------------------------------------------------
# TTS resolution (matches config/schema.py)
# ---------------------------------------------------------


def _resolve_piper_model(cfg, lang: str, voice_id: str) -> str:
    tools = getattr(cfg, "tools", None)
    if not tools:
        return ""

    voices_dir = str(getattr(tools, "piper_voices_dir", "") or "").strip()
    if voices_dir and voice_id:
        cand = Path(voices_dir).expanduser() / f"{voice_id}.onnx"
        if cand.exists():
            return str(cand)
        # strict: if explicitly requested but missing, do not silently swap
        return ""

    if (lang or "").lower().startswith("it"):
        return str(getattr(tools, "piper_model_it", "") or "").strip()
    return str(getattr(tools, "piper_model_en", "") or "").strip()


def _get_voice_ids(cfg, lang: str) -> tuple[str, str]:
    pcfg = getattr(cfg, "podcast", None)
    voices = getattr(pcfg, "voices", None) if pcfg else None

    narrator_id = ""
    expert_id = ""
    try:
        v = getattr(voices, lang)
        narrator_id = str(getattr(getattr(v, "narrator", None), "voice_id", "") or "")
        expert_id = str(getattr(getattr(v, "expert", None), "voice_id", "") or "")
    except Exception:
        narrator_id = ""
        expert_id = ""

    return narrator_id.strip(), expert_id.strip()


async def _run(cmd: list[str], timeout_s: float) -> tuple[int, str, str]:
    p = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(p.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            p.kill()
        except Exception:
            pass
        raise RuntimeError(f"Command timed out after {timeout_s:.0f}s: {' '.join(cmd[:4])} ...")
    out = (out_b or b"").decode("utf-8", errors="replace")
    err = (err_b or b"").decode("utf-8", errors="replace")
    return int(p.returncode or 0), out, err


async def _synthesize_piper(cfg, text: str, lang: str, voice_id: str, out_wav: Path) -> None:
    tools = getattr(cfg, "tools", None)
    piper_bin = str(getattr(tools, "piper_bin", "") or "piper").strip() or "piper"

    model_path = _resolve_piper_model(cfg, lang, voice_id)
    if not model_path:
        raise RuntimeError(f"missing piper model for voice_id={voice_id!r} lang={lang!r}")

    out_wav.parent.mkdir(parents=True, exist_ok=True)

    piper_path = Path(piper_bin).expanduser()
    piper_lib = str((piper_path.parent / "lib").resolve())
    espeak_data = str((piper_path.parent / "share" / "espeak-ng-data").resolve())

    env = dict(os.environ)
    old_ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = (piper_lib + (":" + old_ld if old_ld else ""))
    env.setdefault("ESPEAK_DATA_PATH", espeak_data)

    _pod_dbg(cfg, f"piper model={model_path} (lang={lang}, voice_id={voice_id})")

    cmd = [piper_bin, "--model", model_path, "--output_file", str(out_wav)]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    timeout_s = float(getattr(getattr(cfg, "ollama", None), "timeout_s", 120.0) or 120.0)
    try:
        _out_b, err_b = await asyncio.wait_for(proc.communicate(input=(text or "").encode("utf-8")), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError("piper timeout")

    if int(proc.returncode or 0) != 0:
        err = (err_b or b"").decode("utf-8", errors="replace")
        _pod_dbg(cfg, "piper failed (see stderr for details)")
        print(err, file=sys.stderr)
        raise RuntimeError("piper failed")


async def _synthesize_qwen_tts(cfg, text: str, voice_id: str, out_wav: Path) -> None:
    tools = getattr(cfg, "tools", None)
    qbin = str(getattr(tools, "qwen_tts_bin", "") or "").strip()
    model_dir = str(getattr(tools, "qwen_tts_model_dir", "") or "").strip()
    if not qbin or not model_dir:
        raise RuntimeError("qwen_tts_bin/qwen_tts_model_dir not configured")

    out_wav.parent.mkdir(parents=True, exist_ok=True)

    cmd = [qbin, "--model_dir", model_dir, "--voice", voice_id, "--text", text, "--out", str(out_wav)]
    timeout_s = float(getattr(getattr(cfg, "ollama", None), "timeout_s", 120.0) or 120.0)
    rc, _out, err = await _run(cmd, timeout_s=timeout_s)
    if rc != 0:
        raise RuntimeError(f"qwen_tts failed: {err.strip()[:240]}")


# ---------------------------------------------------------
# Script parsing (robust, deterministic)
# ---------------------------------------------------------

def _sanitize_script(script: str) -> str:
    t = (script or "").strip()
    if not t:
        return ""

    t = re.sub(r"```.*?```", "", t, flags=re.S)
    t = t.strip().strip('"').strip("'").strip()

    # force labels to new lines if mid-line
    t = re.sub(r"(?i)\s+(NARRATOR|EXPERT)\s*:\s*", r"\n\1: ", t)

    # keep from first label
    m = re.search(r"(?im)^(NARRATOR|EXPERT)\s*:", t)
    if m:
        t = t[m.start() :].strip()

    kept: list[str] = []
    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^(NARRATOR|EXPERT)\s*:\s*", line, flags=re.I):
            kept.append(line)
    return "\n".join(kept).strip()


def _parse_dialogue(script: str) -> list[tuple[str, str]]:
    t = _sanitize_script(script)
    if not t:
        return []

    blocks: list[tuple[str, str]] = []
    rx = re.compile(r"(?ims)^(NARRATOR|EXPERT)\s*:\s*(.*?)(?=^\s*(?:NARRATOR|EXPERT)\s*:|\Z)")
    for m in rx.finditer(t):
        spk = m.group(1).upper()
        body = (m.group(2) or "").strip()
        if body:
            body = re.sub(r"\s+", " ", body).strip()
            blocks.append((spk, body))

    # guarantee both speakers (safe)
    spks = {spk for spk, _ in blocks}
    if blocks and "NARRATOR" not in spks:
        blocks[0] = ("NARRATOR", blocks[0][1])
    spks = {spk for spk, _ in blocks}
    if blocks and "EXPERT" not in spks:
        blocks.append(("EXPERT", blocks[-1][1]))

    return blocks


def _merge_same_speaker(parts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not parts:
        return []
    out: list[tuple[str, str]] = []
    cur_spk, cur_txt = parts[0]
    for spk, txt in parts[1:]:
        if spk == cur_spk:
            cur_txt = (cur_txt + " " + (txt or "")).strip()
        else:
            out.append((cur_spk, (cur_txt or "").strip()))
            cur_spk, cur_txt = spk, (txt or "").strip()
    out.append((cur_spk, (cur_txt or "").strip()))
    return [(spk, txt) for spk, txt in out if txt]


def _enforce_word_cap(parts: list[tuple[str, str]], hard_cap_words: int) -> list[tuple[str, str]]:
    cap = max(80, int(hard_cap_words or 0))
    if cap <= 0:
        return parts
    out: list[tuple[str, str]] = []
    used = 0
    for spk, txt in parts:
        words = (txt or "").split()
        if not words:
            continue
        remaining = cap - used
        if remaining <= 0:
            break
        if len(words) > remaining:
            words = words[:remaining]
        out.append((spk, " ".join(words)))
        used += len(words)
    return out


def _split_for_tts(text: str, max_chars: int = 320) -> list[str]:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return []
    max_chars = max(120, int(max_chars))

    parts = re.split(r"(?<=[\.\!\?])\s+", t)
    out: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not buf:
            buf = p
            continue
        if len(buf) + 1 + len(p) <= max_chars:
            buf = buf + " " + p
        else:
            out.append(buf)
            buf = p
    if buf:
        out.append(buf)

    final: list[str] = []
    for c in out:
        if len(c) <= max_chars:
            final.append(c)
        else:
            for i in range(0, len(c), max_chars):
                final.append(c[i : i + max_chars].strip())
    return [x for x in final if x]


def _concat_wavs(wavs: list[Path], out_wav: Path, ffmpeg_bin: str) -> None:
    if not wavs:
        raise RuntimeError("no wav segments")

    params = None
    frames: list[bytes] = []
    try:
        for seg in wavs:
            with wave.open(str(seg), "rb") as w:
                if params is None:
                    params = w.getparams()
                else:
                    if (
                        w.getnchannels() != params.nchannels
                        or w.getsampwidth() != params.sampwidth
                        or w.getframerate() != params.framerate
                    ):
                        raise RuntimeError("wav params mismatch")
                frames.append(w.readframes(w.getnframes()))

        if params is None:
            raise RuntimeError("no wav params")

        out_wav.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_wav), "wb") as wout:
            wout.setnchannels(params.nchannels)
            wout.setsampwidth(params.sampwidth)
            wout.setframerate(params.framerate)
            for fr in frames:
                wout.writeframes(fr)
        return
    except Exception:
        pass

    ff = (ffmpeg_bin or "ffmpeg").strip() or "ffmpeg"
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    lst = out_wav.with_suffix(".concat.txt")
    abs_lines = []
    for seg in wavs:
        ap = str(seg.resolve()).replace("'", "'\\''")
        abs_lines.append(f"file '{ap}'")
    lst.write_text("\n".join(abs_lines) + "\n", encoding="utf-8")

    cmd = [
        ff,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(lst),
        "-ac",
        "1",
        "-ar",
        "22050",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------
# Main generator (uses cfg.podcast + cfg.tools; prompts centralized)
# ---------------------------------------------------------

async def generate_podcast(cfg, provider, topic: str, lang: str, status: StatusCb | None = None) -> PodcastResult:
    pcfg = getattr(cfg, "podcast", None)
    if not pcfg or not getattr(pcfg, "enabled", False):
        raise RuntimeError("podcast disabled")

    default_minutes = int(getattr(pcfg, "default_minutes", 1) or 1)
    max_minutes = int(getattr(pcfg, "max_minutes", 2) or 2)
    target_wpm = int(getattr(pcfg, "target_words_per_minute", 150) or 150)

    minutes = max(1, min(default_minutes, max_minutes))
    hard_cap_words = int(max_minutes * target_wpm)
    target_words = int(minutes * target_wpm)
    target_words = max(80, min(target_words, hard_cap_words))

    # outputs/podcasts/<stamp>_<slug>/...
    base_out = Path(getattr(pcfg, "output_dir", "outputs/podcasts") or "outputs/podcasts").expanduser()
    run_name = f"{_utc_stamp()}_{_slug(topic)}"
    run_dir = (base_out / run_name).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    keep_segments = bool(getattr(pcfg, "keep_segments", False))

    if status:
        await status("🎙 Writing script…")

    duration_s = int(minutes * 60)

    resp = await provider.chat(
        messages=[
            {"role": "system", "content": podcast_system_prompt(lang=lang, duration_s=duration_s)},
            {"role": "user", "content": podcast_user_prompt(lang=lang, topic=topic, duration_s=duration_s)},
        ],
        tools=None,
        max_tokens=900,
        temperature=0.0,
    )

    script = (resp.content or "").strip()
    _pod_dbg(cfg, f"llm script chars={len(script)}")

    parts = _merge_same_speaker(_parse_dialogue(script))
    parts = _merge_same_speaker(_enforce_word_cap(parts, hard_cap_words))
    if not parts:
        raise RuntimeError("bad script format")

    # persist script + meta (always)
    (run_dir / "script.txt").write_text(script + "\n", encoding="utf-8")
    meta = {
        "topic": topic,
        "lang": lang,
        "minutes": minutes,
        "target_words": target_words,
        "hard_cap_words": hard_cap_words,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if status:
        await status("🗣 Synthesizing audio…")

    narrator_id, expert_id = _get_voice_ids(cfg, lang)
    tts_backend = str(getattr(pcfg, "tts_backend", "piper") or "piper").strip().lower()

    if narrator_id == expert_id and narrator_id:
        raise RuntimeError("podcast voices must be different (narrator != expert)")

    if tts_backend == "qwen_tts":
        if not narrator_id or not expert_id:
            raise RuntimeError("qwen_tts requires narrator/expert voice_id in config")
    else:
        if narrator_id and not _resolve_piper_model(cfg, lang, narrator_id):
            raise RuntimeError("missing narrator voice model")
        if expert_id and not _resolve_piper_model(cfg, lang, expert_id):
            raise RuntimeError("missing expert voice model")

    seg_dir = run_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    seg_paths: list[Path] = []
    seg_i = 0
    for spk, txt in parts:
        voice_id = narrator_id if spk == "NARRATOR" else expert_id
        subchunks = _split_for_tts(txt, max_chars=320)

        for chunk in subchunks:
            seg_i += 1
            wav_path = seg_dir / f"seg_{seg_i:03d}_{spk.lower()}.wav"
            if tts_backend == "qwen_tts":
                await _synthesize_qwen_tts(cfg, chunk, voice_id=voice_id, out_wav=wav_path)
            else:
                await _synthesize_piper(cfg, chunk, lang=lang, voice_id=voice_id, out_wav=wav_path)
            seg_paths.append(wav_path)

    tools = getattr(cfg, "tools", None)
    ffmpeg_bin = str(getattr(tools, "ffmpeg_bin", "ffmpeg") or "ffmpeg")

    merged_wav = run_dir / "podcast.wav"
    _concat_wavs(seg_paths, merged_wav, ffmpeg_bin=ffmpeg_bin)

    fmt = str(getattr(pcfg, "audio_format", "mp3") or "mp3").lower().strip()
    if fmt not in {"mp3", "ogg", "wav"}:
        fmt = "mp3"

    final_path = merged_wav
    if fmt != "wav":
        final_path = run_dir / f"podcast.{fmt}"
        cmd = [ffmpeg_bin, "-y", "-i", str(merged_wav), str(final_path)]
        timeout_s = float(getattr(getattr(cfg, "ollama", None), "timeout_s", 120.0) or 120.0)
        rc, _out, err = await _run(cmd, timeout_s=timeout_s)
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed: {err.strip()[:240]}")

    if not keep_segments:
        try:
            for p in seg_dir.glob("*.wav"):
                p.unlink(missing_ok=True)
            seg_dir.rmdir()
        except Exception:
            pass

    if status:
        await status("✅ Podcast ready")

    return PodcastResult(audio_path=str(final_path), script=script, run_dir=str(run_dir))
