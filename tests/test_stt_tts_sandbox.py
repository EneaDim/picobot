import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from picobot.tools.stt import transcribe_audio_file
from picobot.tools.tts import synthesize_speech


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeTerminalToolBase:
    def __init__(self, *, cfg=None, allowed_bins=None, timeout_s=0, max_output_bytes=0, extra_env=None):
        self.cfg = cfg
        self.allowed_bins = allowed_bins or []
        self.timeout_s = timeout_s
        self.max_output_bytes = max_output_bytes
        self.extra_env = extra_env or {}
        self.workspace_root = Path(cfg.workspace).expanduser().resolve()
        self.backend = "local"

    def resolve_workspace_path(self, value):
        p = Path(str(value)).expanduser()
        target = p.resolve() if p.is_absolute() else (self.workspace_root / p).resolve()
        if not str(target).startswith(str(self.workspace_root)):
            raise ValueError("outside workspace")
        return target

    def map_host_path(self, path):
        return str(Path(path).resolve())

    def run_cmd(self, argv, *, prefix, timeout_s=None, input_bytes=None, env=None, relative_cwd=None):
        if prefix == "[stt]":
            base = Path(argv[argv.index("-of") + 1])
            base.with_suffix(".txt").write_text("Trascrizione di prova: NEMO-77", encoding="utf-8")
            return _FakeResult(0, "", "")

        if prefix == "[tts]":
            out = Path(argv[argv.index("--output_file") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"RIFF....WAVE")
            return _FakeResult(0, "", "")

        return _FakeResult(1, "", "unexpected prefix")


def _cfg(workspace: Path):
    return SimpleNamespace(
        workspace=str(workspace),
        sandbox=SimpleNamespace(
            runtime=SimpleNamespace(
                backend="local",
                workspace_root=str(workspace),
            )
        ),
        tools=SimpleNamespace(),
    )


def test_stt_uses_sandbox_runner_and_writes_artifacts(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    whisper_bin = tmp_path / "whisper-cli"
    whisper_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    whisper_bin.chmod(0o755)

    whisper_model = tmp_path / "ggml-small.bin"
    whisper_model.write_bytes(b"model")

    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFF....WAVE")

    cfg = _cfg(workspace)

    monkeypatch.setattr("picobot.tools.stt.TerminalToolBase", _FakeTerminalToolBase)
    monkeypatch.setattr("picobot.tools.stt.get_runtime_tool_bin", lambda cfg, key, default: str(whisper_bin))
    monkeypatch.setattr("picobot.tools.stt.get_tool_model", lambda cfg, key, default: str(whisper_model))

    result = asyncio.run(transcribe_audio_file(cfg, audio_path=audio, lang="it"))

    assert result.ok is True
    assert result.backend == "local"
    assert "NEMO-77" in result.text
    assert Path(result.transcript_path).exists()
    assert Path(result.meta_path).exists()

    payload = json.loads(Path(result.meta_path).read_text(encoding="utf-8"))
    assert payload["backend"] == "local"
    assert str(Path(result.transcript_path).resolve()).startswith(str(workspace.resolve()))


def test_tts_uses_sandbox_runner_and_writes_artifacts(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    piper_bin = tmp_path / "piper"
    piper_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    piper_bin.chmod(0o755)

    piper_model = tmp_path / "voice.onnx"
    piper_model.write_bytes(b"model")

    cfg = _cfg(workspace)

    monkeypatch.setattr("picobot.tools.tts.TerminalToolBase", _FakeTerminalToolBase)
    monkeypatch.setattr("picobot.tools.tts.get_runtime_tool_bin", lambda cfg, key, default: str(piper_bin))
    monkeypatch.setattr(
        "picobot.tools.tts._pick_model",
        lambda cfg, lang, voice_id=None: str(piper_model),
    )

    audio_path = synthesize_speech(
        cfg,
        "Ciao dal progetto NEMO-77",
        lang="it",
        voice_id="it_IT-paola-medium",
    )

    audio = Path(audio_path)
    meta = audio.with_suffix(".tts.meta.json")

    assert audio.exists()
    assert meta.exists()

    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["backend"] == "local"
    assert payload["voice_id"] == "it_IT-paola-medium"
    assert str(audio.resolve()).startswith(str(workspace.resolve()))
