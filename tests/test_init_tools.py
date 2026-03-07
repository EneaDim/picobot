import json
from pathlib import Path

from picobot.tools.init_tools import init_tool_dirs, resolve_config_path, tool_snapshot


def test_resolve_config_path_prefers_local_file(tmp_path: Path, monkeypatch):
    cfg_dir = tmp_path / ".picobot"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = cfg_dir / "config.json"
    cfg_path.write_text(json.dumps({"tools": {"base_dir": str(tmp_path / ".picobot/tools")}}), encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    resolved = resolve_config_path(None)
    assert resolved == cfg_path.resolve()


def test_init_tool_dirs_and_snapshot(tmp_path: Path):
    cfg_dir = tmp_path / ".picobot"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = cfg_dir / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "tools": {
                    "base_dir": str(tmp_path / ".picobot/tools"),
                    "bins": {
                        "ytdlp": str(tmp_path / ".picobot/tools/yt-dlp/bin/yt-dlp"),
                        "ffmpeg": "ffmpeg",
                        "piper": str(tmp_path / ".picobot/tools/piper/bin/piper"),
                    },
                    "models": {
                        "piper_it": str(tmp_path / ".picobot/tools/piper/models/it.onnx"),
                        "piper_en": str(tmp_path / ".picobot/tools/piper/models/en.onnx"),
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    result = init_tool_dirs(cfg_path)
    assert result["ok"] is True

    snapshot = tool_snapshot(cfg_path)
    assert "bins" in snapshot
    assert "models" in snapshot
    assert snapshot["tools_root"]
