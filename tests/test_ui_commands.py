from pathlib import Path

from picobot.config.schema import Config
from picobot.session.manager import SessionManager
from picobot.ui import handle_command


def test_mem_show_and_clear(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    sm = SessionManager(workspace)
    session = sm.get("test")
    cfg = Config(workspace=str(workspace))

    result_show = handle_command(
        "/mem show",
        session=session,
        session_manager=sm,
        cfg=cfg,
        workspace=workspace,
    )
    assert result_show.handled is True
    assert "MEMORY" in result_show.reply

    result_clear = handle_command(
        "/mem clear",
        session=session,
        session_manager=sm,
        cfg=cfg,
        workspace=workspace,
    )
    assert result_clear.handled is True
    assert "pulite" in result_clear.reply.lower()


def test_news_passthrough(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    sm = SessionManager(workspace)
    session = sm.get("test")
    cfg = Config(workspace=str(workspace))

    result = handle_command(
        "/news intelligenza artificiale",
        session=session,
        session_manager=sm,
        cfg=cfg,
        workspace=workspace,
    )
    assert result.handled is False
