from pathlib import Path

from picobot.session.manager import sanitize_session_id, SessionManager


def test_sanitize_session_id():
    assert sanitize_session_id("  hello world ") == "hello-world"
    assert sanitize_session_id("!!!") == "default"


def test_session_manager_creates_files(tmp_path: Path):
    sm = SessionManager(tmp_path)
    s = sm.get("abc")
    assert s.history_file.exists()
    assert s.summary_file.exists()
    assert s.memory_file.exists()
