from __future__ import annotations

import json
from pathlib import Path

from picobot.memory.manager import make_memory_manager
from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.query import query_kb
from picobot.retrieval.store import copy_source_file, list_kbs, sanitize_kb_name
from picobot.session.manager import SessionManager
from picobot.ui.command_models import CommandResult


def read_text(path: Path) -> str:
    if not path.exists():
        return "(vuoto)"
    data = path.read_text(encoding="utf-8").strip()
    return data or "(vuoto)"


def active_kb_name(*, cfg, session) -> str:
    state = session.get_state()
    default_name = getattr(getattr(cfg, "kb", None), "default_name", None)
    if not default_name:
        default_name = getattr(cfg, "default_kb_name", "default")
    return sanitize_kb_name(str(state.get("kb_name") or default_name or "default"))


def format_kb_query_result(*, kb_name: str, query: str, result) -> str:
    lines = [
        f"KB query result [{kb_name}]",
        f"- query: {query}",
        f"- hits: {len(result.hits)}",
        f"- max_score: {result.max_score:.4f}",
    ]

    if result.hits:
        lines.append("- top results:")
        for idx, hit in enumerate(result.hits, start=1):
            snippet = " ".join((hit.text or "").split())
            if len(snippet) > 160:
                snippet = snippet[:157].rstrip() + "..."

            page = ""
            if hit.page_start is not None and hit.page_end is not None:
                page = (
                    f" p.{hit.page_start}"
                    if hit.page_start == hit.page_end
                    else f" p.{hit.page_start}-{hit.page_end}"
                )

            lines.append(
                f"  {idx}. {hit.source_file}{page} | score={hit.fused_score:.4f} | {snippet}"
            )
    else:
        lines.append("- top results: (nessuno)")

    context = (result.context or "").strip()
    if context:
        lines.append("")
        lines.append("Context:")
        lines.append(context)

    return "\n".join(lines)


def handle_kb_ingest(*, arg: str, cfg, workspace: Path, session) -> CommandResult:
    src = Path(arg).expanduser()
    if not src.is_absolute():
        src = (Path.cwd() / src).resolve()
    else:
        src = src.resolve()

    if not src.exists() or not src.is_file():
        return CommandResult(handled=True, text=f"File non trovato: {src}")

    if src.suffix.lower() != ".pdf":
        return CommandResult(handled=True, text="/kb ingest supporta solo file PDF")

    kb_name = active_kb_name(cfg=cfg, session=session)

    try:
        copied = copy_source_file(workspace, kb_name, src)
        result = ingest_kb(workspace=workspace, kb_name=kb_name)
    except Exception as exc:
        return CommandResult(handled=True, text=f"Errore /kb ingest: {exc}")

    lines = [
        f"KB ingest completato [{result.kb_name}]",
        f"- source file copiato: {copied}",
        f"- source_files: {result.source_files}",
        f"- chunk_files: {result.chunk_files}",
        f"- indexed_points: {result.indexed_points}",
        f"- manifest: {result.manifest_path}",
    ]
    return CommandResult(handled=True, text="\n".join(lines))


def handle_mem_clean(*, cfg, workspace: Path, session) -> CommandResult:
    try:
        mm = make_memory_manager(cfg, session, workspace)
        mm.clear_all()
    except Exception as exc:
        return CommandResult(handled=True, text=f"Errore /mem clean: {exc}")

    lines = [
        "Memoria della chat ripulita.",
        "- state.json: reset",
        "- HISTORY.md / history.jsonl: svuotati",
        "- SUMMARY.md / summary.json: reset",
        "- MEMORY.md / facts.jsonl: svuotati",
    ]
    return CommandResult(handled=True, text="\n".join(lines))


def handle_kb_query(*, arg: str, cfg, workspace: Path, session) -> CommandResult:
    query = (arg or "").strip()
    if not query:
        return CommandResult(handled=True, text="Uso: /kb query <testo>")

    kb_name = active_kb_name(cfg=cfg, session=session)

    try:
        result = query_kb(
            workspace=workspace,
            kb_name=kb_name,
            query=query,
            top_k=4,
        )
    except Exception as exc:
        return CommandResult(handled=True, text=f"Errore /kb query: {exc}")

    return CommandResult(
        handled=True,
        text=format_kb_query_result(kb_name=kb_name, query=query, result=result),
    )


def load_session(*, workspace: Path, session_id: str):
    sessions = SessionManager(workspace)
    return sessions.get(session_id)


def dump_session_state(session) -> str:
    return "Session state:\n" + json.dumps(session.get_state(), indent=2, ensure_ascii=False)


def list_registered_tools(orchestrator) -> str:
    names = sorted(orchestrator.tools.list())
    return "Tools registrati:\n- " + "\n- ".join(names)


def kb_list_text(workspace: Path) -> str:
    names = list_kbs(Path(workspace))
    return "KB disponibili:\n- " + ("\n- ".join(names) if names else "(nessuna)")
