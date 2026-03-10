from pathlib import Path

from picobot.config.schema import Config
from picobot.retrieval.schemas import IngestResult, QueryHit, QueryResult
from picobot.ui import handle_local_command


def _make_cfg(workspace: Path) -> Config:
    return Config(workspace=str(workspace))


def test_mem_returns_session_state(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    result = handle_local_command(
        raw_text="/mem",
        cfg=_make_cfg(workspace),
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.bus_text is None
    assert result.text is not None
    assert "Session state:" in result.text


def test_mem_clean_clears_saved_chat_memory(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    result_use = handle_local_command(
        raw_text="/kb use demo-kb",
        cfg=_make_cfg(workspace),
        workspace=workspace,
        session_id="test",
    )
    assert result_use.handled is True

    session_root = workspace / "memory" / "sessions" / "test"
    (session_root / "HISTORY.md").write_text("# Session History\n\n- messaggio\n", encoding="utf-8")
    (session_root / "history.jsonl").write_text('{"role":"user","content":"ciao"}\n', encoding="utf-8")
    (session_root / "SUMMARY.md").write_text("# Session Summary\n\nriassunto\n", encoding="utf-8")
    (session_root / "summary.json").write_text('{"summary_text":"riassunto"}', encoding="utf-8")
    (workspace / "memory" / "MEMORY.md").write_text("# Memory\n\n- fatto\n", encoding="utf-8")
    (workspace / "memory" / "facts.jsonl").write_text('{"fact":"fatto"}\n', encoding="utf-8")

    result = handle_local_command(
        raw_text="/mem clean",
        cfg=_make_cfg(workspace),
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.bus_text is None
    assert result.text is not None
    assert "Memoria della chat ripulita." in result.text
    assert '"kb_name": "demo-kb"' not in (session_root / "state.json").read_text(encoding="utf-8")
    assert (session_root / "HISTORY.md").read_text(encoding="utf-8") == "# Session History\n\n"
    assert (session_root / "history.jsonl").read_text(encoding="utf-8") == ""
    assert (session_root / "SUMMARY.md").read_text(encoding="utf-8") == "# Session Summary\n"
    assert "summary_text" in (session_root / "summary.json").read_text(encoding="utf-8")
    assert (workspace / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "# Memory\n\n"
    assert (workspace / "memory" / "facts.jsonl").read_text(encoding="utf-8") == ""


def test_news_passthrough(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    result = handle_local_command(
        raw_text="/news intelligenza artificiale",
        cfg=_make_cfg(workspace),
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.bus_text == "/news intelligenza artificiale"


def test_kb_use_sanitizes_name(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    result = handle_local_command(
        raw_text="/kb use Demo KB 2026!.pdf",
        cfg=_make_cfg(workspace),
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.text == "KB attiva impostata a: Demo-KB-2026"


def test_kb_ingest_is_local_and_deterministic(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    source_pdf = tmp_path / "invented.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n% fake test payload\n")

    calls: dict[str, object] = {}

    def fake_ingest_kb(*, workspace: Path, kb_name: str) -> IngestResult:
        calls["workspace"] = workspace
        calls["kb_name"] = kb_name
        return IngestResult(
            kb_name=kb_name,
            source_files=1,
            chunk_files=3,
            indexed_points=3,
            manifest_path=str(Path(workspace) / "docs" / kb_name / "kb" / "manifest.json"),
        )

    monkeypatch.setattr("picobot.ui.commands.ingest_kb", fake_ingest_kb)

    result = handle_local_command(
        raw_text=f"/kb ingest {source_pdf}",
        cfg=_make_cfg(workspace),
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.bus_text is None
    assert calls["workspace"] == workspace
    assert calls["kb_name"] == "default"
    assert result.text is not None
    assert "KB ingest completato [default]" in result.text
    assert (workspace / "docs" / "default" / "source" / source_pdf.name).exists()


def test_kb_query_is_local_and_deterministic(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    calls: dict[str, object] = {}

    def fake_query_kb(*, workspace: Path, kb_name: str, query: str, top_k: int) -> QueryResult:
        calls["workspace"] = workspace
        calls["kb_name"] = kb_name
        calls["query"] = query
        calls["top_k"] = top_k
        return QueryResult(
            hits=[
                QueryHit(
                    chunk_id="demo::000001",
                    fused_score=0.91,
                    text="Il progetto Zaffiro-47 usa il refrigerante narrativo ORBITAL-MINT.",
                    source_file="invented.pdf",
                    page_start=2,
                    page_end=2,
                    section="specifiche",
                    vector_score=0.88,
                    lexical_score=4.2,
                    ranks={"vector": 1, "lexical": 1},
                )
            ],
            context="[source: invented.pdf p.2]\nIl progetto Zaffiro-47 usa il refrigerante narrativo ORBITAL-MINT.",
            max_score=0.91,
        )

    monkeypatch.setattr("picobot.ui.commands.query_kb", fake_query_kb)

    result = handle_local_command(
        raw_text="/kb query qual è il refrigerante del progetto Zaffiro-47?",
        cfg=_make_cfg(workspace),
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.bus_text is None
    assert calls == {
        "workspace": workspace,
        "kb_name": "default",
        "query": "qual è il refrigerante del progetto Zaffiro-47?",
        "top_k": 4,
    }
    assert result.text is not None
    assert "KB query result [default]" in result.text
    assert "ORBITAL-MINT" in result.text
    assert "Context:" in result.text
