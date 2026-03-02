from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from picobot.agent.prompts import PromptPack, detect_language, podcast_system

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


def detect_podcast_request(text: str, cfg) -> tuple[str, str] | None:
    t = (text or "").strip()
    if not t:
        return None

    default_lang = getattr(cfg, "default_language", "it")
    lang = detect_language(t, default=default_lang)

    pcfg = getattr(cfg, "podcast", None)
    if not pcfg or not getattr(pcfg, "enabled", False):
        return None

    triggers = getattr(pcfg, "triggers", None)
    if not triggers:
        return None

    try:
        trig_list = list(getattr(triggers, lang))
    except Exception:
        trig_list = []

    low = t.lower()
    for trig in trig_list:
        trig_low = (trig or "").strip().lower()
        if trig_low and low.startswith(trig_low):
            topic = t[len(trig) :].strip(" \t\n\r:,-")
            return (topic or "podcast", lang)

    return None


@dataclass(frozen=True)
class PodcastResult:
    audio_path: str
    script: str


def _resolve_piper_model(cfg, lang: str, voice_id: str) -> str:
    tools = getattr(cfg, "tools", None)
    if not tools:
        return ""

    voices_dir = str(getattr(tools, "piper_voices_dir", "") or "").strip()
    if voices_dir and voice_id:
        cand = Path(voices_dir).expanduser() / f"{voice_id}.onnx"
        if cand.exists():
            return str(cand)
        # STRICT: if a voice_id is explicitly requested, do not silently swap to another voice
        return ""

    # If no voice_id was set, fall back to a language-default model path
    if (lang or "").lower().startswith("it"):
        return str(getattr(tools, "piper_model_it", "") or "")
    return str(getattr(tools, "piper_model_en", "") or "")


def _get_voice_ids(cfg, lang: str) -> tuple[str, str]:
    """Return (narrator_id, expert_id). Empty strings mean 'not configured'."""
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

    narrator_id = narrator_id.strip()
    expert_id = expert_id.strip()
    return narrator_id, expert_id


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

    # keep only labeled lines
    kept: list[str] = []
    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^(NARRATOR|EXPERT)\s*:\s*", line, flags=re.I):
            kept.append(line)
    t = "\n".join(kept).strip()
    if not t:
        return ""

    # drop meta-intro narrator lines
    tlines = t.splitlines()
    if tlines and tlines[0].upper().startswith("NARRATOR:"):
        body = tlines[0][len("NARRATOR:") :].strip().lower()
        if ("ecco" in body) or ("dialogo" in body) or ("oggi abbiamo" in body) or ("breve" in body):
            tlines = tlines[1:]

    cleaned: list[str] = []
    for ln in tlines:
        if ln.upper().startswith("NARRATOR:"):
            body = ln[len("NARRATOR:") :].strip().lower()
            if body.startswith("ecco") or ("ecco" in body and len(body.split()) <= 10):
                continue
        cleaned.append(ln)

    return "\n".join(cleaned).strip()


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

    if not blocks:
        plain = re.sub(r"\s+", " ", t).strip()
        if not plain:
            return []
        words = plain.split()
        mid = max(10, len(words) // 2)
        blocks = [("NARRATOR", " ".join(words[:mid]).strip()), ("EXPERT", " ".join(words[mid:]).strip())]

    spks = {spk for spk, _ in blocks}
    if "NARRATOR" not in spks and blocks:
        blocks[0] = ("NARRATOR", blocks[0][1])
    spks = {spk for spk, _ in blocks}
    if "EXPERT" not in spks and blocks:
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

    # Try direct concat only if all params match
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

    # Fallback: normalize+concat via ffmpeg
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

    audience = str(getattr(pcfg, "audience", "general") or "general")
    style = str(getattr(pcfg, "style", "warm, curious, practical") or "warm, curious, practical")

    if status:
        await status("🎙 Writing script…")

    pp = PromptPack(lang=lang)
    prompt = pp.podcast_writer(
        topic=topic,
        target_words=target_words,
        hard_cap_words=hard_cap_words,
        audience=audience,
        style=style,
    )

    resp = await provider.chat(
        messages=[
            {"role": "system", "content": podcast_system(lang)},
            {"role": "user", "content": prompt},
        ],
        tools=None,
        max_tokens=900,
        temperature=0.0,
    )

    script = (resp.content or "").strip()
    _pod_dbg(cfg, f"llm script chars={len(script)}")
    _pod_dbg(cfg, (script[:1200] + ("..." if len(script) > 1200 else "")))

    parts = _merge_same_speaker(_parse_dialogue(script))
    parts = _merge_same_speaker(_enforce_word_cap(parts, hard_cap_words))
    _pod_dbg(cfg, f"parsed parts={len(parts)} speakers={[sp for sp, _ in parts]}")
    if not parts:
        raise RuntimeError("bad script format")

    if status:
        await status("🗣 Synthesizing audio…")

    out_dir = Path(getattr(pcfg, "output_dir", "outputs/podcasts") or "outputs/podcasts").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    narrator_id, expert_id = _get_voice_ids(cfg, lang)
    tts_backend = str(getattr(pcfg, "tts_backend", "piper") or "piper").strip().lower()

    if tts_backend == "qwen_tts":
        if not narrator_id or not expert_id:
            raise RuntimeError("qwen_tts requires narrator/expert voice_id in config")
        if narrator_id == expert_id:
            _pod_dbg(cfg, "WARNING: narrator/expert voice_id are identical (same voice).")
    else:
        # Piper: require explicit voice ids OR accept language defaults if you configured piper_model_{it,en}
        nm = _resolve_piper_model(cfg, lang, narrator_id)
        em = _resolve_piper_model(cfg, lang, expert_id)
        if narrator_id and not nm:
            _pod_dbg(cfg, f"Missing narrator voice model for voice_id={narrator_id!r}")
            raise RuntimeError("missing narrator voice model")
        if expert_id and not em:
            _pod_dbg(cfg, f"Missing expert voice model for voice_id={expert_id!r}")
            raise RuntimeError("missing expert voice model")

        # If voice ids are not configured, we will synthesize both with language-default model.
        if not narrator_id:
            narrator_id = ""
        if not expert_id:
            expert_id = ""

        if narrator_id and expert_id and narrator_id == expert_id:
            _pod_dbg(cfg, "WARNING: narrator/expert voice_id are identical (same voice).")

    seg_paths: list[Path] = []
    seg_i = 0
    for spk, txt in parts:
        voice_id = narrator_id if spk == "NARRATOR" else expert_id
        _pod_dbg(cfg, f"voice {spk} voice_id={voice_id!r}")

        subchunks = _split_for_tts(txt, max_chars=320)
        _pod_dbg(cfg, f"{spk} chunks={len(subchunks)}")

        for chunk in subchunks:
            seg_i += 1
            wav_path = out_dir / f"seg_{seg_i:03d}_{spk.lower()}.wav"

            if tts_backend == "qwen_tts":
                await _synthesize_qwen_tts(cfg, chunk, voice_id=voice_id, out_wav=wav_path)
            else:
                await _synthesize_piper(cfg, chunk, lang=lang, voice_id=voice_id, out_wav=wav_path)

            seg_paths.append(wav_path)

    tools = getattr(cfg, "tools", None)
    ffmpeg_bin = str(getattr(tools, "ffmpeg_bin", "ffmpeg") or "ffmpeg")

    merged_wav = out_dir / "podcast.wav"
    _concat_wavs(seg_paths, merged_wav, ffmpeg_bin=ffmpeg_bin)

    fmt = str(getattr(pcfg, "audio_format", "mp3") or "mp3").lower().strip()
    if fmt not in {"mp3", "ogg", "wav"}:
        fmt = "mp3"

    final_path = merged_wav
    if fmt != "wav":
        final_path = out_dir / f"podcast.{fmt}"
        cmd = [ffmpeg_bin, "-y", "-i", str(merged_wav), str(final_path)]
        timeout_s = float(getattr(getattr(cfg, "ollama", None), "timeout_s", 120.0) or 120.0)
        rc, _out, err = await _run(cmd, timeout_s=timeout_s)
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed: {err.strip()[:240]}")

    if status:
        await status("✅ Podcast ready")

    return PodcastResult(audio_path=str(final_path), script=script)
