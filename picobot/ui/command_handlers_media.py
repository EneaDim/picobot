from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from picobot.session.manager import Session
from picobot.ui.command_models import CommandResult


def _resolve_audio_path(text: str, session: Session) -> tuple[Path | None, str | None]:
    raw = (text or "").strip()

    if raw == "/play":
        state = session.get_state()
        last_audio = str(state.get("last_audio_path") or "").strip()
        if not last_audio:
            return None, "Nessun audio recente nella sessione. Genera prima un /tts o un /podcast, oppure usa /play <path>."
        return Path(last_audio).expanduser().resolve(), None

    if raw.startswith("/play "):
        arg = raw[len("/play "):].strip()
        if not arg:
            return None, "Uso: /play oppure /play <path>"
        return Path(arg).expanduser().resolve(), None

    return None, None


def _launch_player(path: Path) -> tuple[bool, str]:
    candidates: list[list[str]] = []

    if shutil.which("mpv"):
        candidates.append(["mpv", "--really-quiet", str(path)])
    if shutil.which("ffplay"):
        candidates.append(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)])
    if shutil.which("paplay"):
        candidates.append(["paplay", str(path)])
    if shutil.which("aplay"):
        candidates.append(["aplay", str(path)])
    if shutil.which("afplay"):
        candidates.append(["afplay", str(path)])

    system = platform.system().lower()

    if system == "darwin":
        candidates.append(["open", str(path)])
    elif system == "windows":
        candidates.append(["powershell", "-NoProfile", "-Command", f'Start-Process "{str(path)}"'])
    else:
        if shutil.which("xdg-open"):
            candidates.append(["xdg-open", str(path)])

    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True, " ".join(cmd[:2]) if len(cmd) >= 2 else cmd[0]
        except Exception:
            continue

    return False, ""


def dispatch_media_command(*, text: str, session: Session) -> CommandResult | None:
    raw = (text or "").strip()
    if raw != "/play" and not raw.startswith("/play "):
        return None

    path, err = _resolve_audio_path(raw, session)
    if err:
        return CommandResult(handled=True, text=err)

    assert path is not None

    if not path.exists():
        return CommandResult(
            handled=True,
            text=f"File audio non trovato: {path}",
        )

    ok, player = _launch_player(path)
    if not ok:
        return CommandResult(
            handled=True,
            text=(
                "Nessun player audio disponibile sul sistema.\n"
                "Installa uno tra: mpv, ffplay, paplay, aplay, afplay.\n"
                f"File pronto da riprodurre: {path}"
            ),
        )

    return CommandResult(
        handled=True,
        text=f"Riproduzione avviata con {player}\nAudio: {path}",
    )
