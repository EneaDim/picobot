from pathlib import Path

from picobot.ui import handle_command
from picobot.config.schema import Config
from picobot.session.manager import SessionManager


def test_news_command_rewrites_to_workflow_text(tmp_path: Path):
    cfg = Config(workspace=str(tmp_path))
    sm = SessionManager(tmp_path)
    session = sm.get("s1")

    res = handle_command(
        "/news intelligenza artificiale europa",
        session=session,
        session_manager=sm,
        cfg=cfg,
        workspace=tmp_path,
    )

    assert res.handled is False
    assert getattr(res, "rewrite_text", "") == "news: intelligenza artificiale europa"
