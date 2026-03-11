from pathlib import Path

from picobot.config.schema import Config
from picobot.ui import handle_local_command
from picobot.ui.command_models import CommandResult


def test_kb_ask_is_passthrough(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    cfg = Config(workspace=str(workspace))

    result = handle_local_command(
        raw_text="/kb ask Dove si trova Serra Vetro?",
        cfg=cfg,
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.bus_text == "/kb ask Dove si trova Serra Vetro?"
    assert result.text is None


def test_kb_query_is_local(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    cfg = Config(workspace=str(workspace))

    import picobot.ui.commands as commands_mod

    def fake_dispatch_kb_command(*, text, cfg, workspace, session, ingest_fn, query_fn):
        if text.startswith("/kb query "):
            return CommandResult(handled=True, text="KB query result [default]")
        return None

    monkeypatch.setattr(commands_mod, "dispatch_kb_command", fake_dispatch_kb_command)

    result = handle_local_command(
        raw_text="/kb query Dove si trova Serra Vetro?",
        cfg=cfg,
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.text == "KB query result [default]"
