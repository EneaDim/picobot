from __future__ import annotations

import inspect
import re
import shutil
from pathlib import Path

from picobot.ui.command_helpers import active_kb_name
from picobot.ui.command_models import CommandResult


def _persist_session_state(session, state: dict) -> None:
    if hasattr(session, "set_state"):
        session.set_state(state)
        return
    if hasattr(session, "save_state"):
        session.save_state(state)
        return
    if hasattr(session, "write_state"):
        session.write_state(state)
        return
    if hasattr(session, "state_file"):
        import json
        Path(session.state_file).write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return
    raise RuntimeError("Impossibile persistere lo stato della sessione: nessun metodo supportato trovato.")


def _kb_name(cfg, session) -> str:
    return active_kb_name(cfg=cfg, session=session)


def _sanitize_kb_name(raw: str) -> str:
    value = str(raw or "").strip()
    if value.lower().endswith(".pdf"):
        value = value[:-4]
    value = re.sub(r"[^A-Za-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "default"


def _call_ingest_kb_compat(*, ingest_fn, kb_name: str, source_path: str, cfg, workspace: Path):
    sig = inspect.signature(ingest_fn)
    params = sig.parameters

    kwargs: dict = {}

    if "workspace" in params:
        kwargs["workspace"] = Path(workspace)
    if "kb_name" in params:
        kwargs["kb_name"] = kb_name
    if "source_path" in params:
        kwargs["source_path"] = source_path
    elif "source_file" in params:
        kwargs["source_file"] = source_path
    elif "path" in params:
        kwargs["path"] = source_path
    elif "pdf_path" in params:
        kwargs["pdf_path"] = source_path

    if "ollama_base_url" in params:
        kwargs["ollama_base_url"] = getattr(cfg.ollama, "base_url", "http://localhost:11434")
    if "embed_model" in params:
        kwargs["embed_model"] = (
            getattr(getattr(cfg, "retrieval", None), "embed_model", None)
            or getattr(cfg.ollama, "embed_model", None)
            or getattr(cfg.ollama, "model", None)
        )

    return ingest_fn(**kwargs)


def _call_query_kb_compat(*, query_fn, kb_name: str, query: str, workspace: Path):
    sig = inspect.signature(query_fn)
    params = sig.parameters

    kwargs: dict = {}

    if "workspace" in params:
        kwargs["workspace"] = Path(workspace)
    if "kb_name" in params:
        kwargs["kb_name"] = kb_name
    if "query" in params:
        kwargs["query"] = query
    if "top_k" in params:
        # Compat legacy: il command layer usa 4 fisso.
        kwargs["top_k"] = 4

    return query_fn(**kwargs)


def _result_value(obj, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _item_value(obj, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_items(result) -> list:
    results = _result_value(result, "results", None)
    if isinstance(results, list):
        return results

    hits = _result_value(result, "hits", None)
    if isinstance(hits, list):
        return hits

    return []


def _normalize_hits_count(result, items: list) -> int:
    hits = _result_value(result, "hits", None)

    if isinstance(hits, int):
        return hits
    if isinstance(hits, float):
        return int(hits)
    if isinstance(hits, list):
        return len(hits)

    count = _result_value(result, "count", None)
    if isinstance(count, int):
        return count
    if isinstance(count, float):
        return int(count)

    return len(items)


def _normalize_max_score(result, items: list) -> float:
    raw = _result_value(result, "max_score", None)
    if isinstance(raw, (int, float)):
        return float(raw)

    best = 0.0
    for item in items:
        try:
            score = float(
                _item_value(item, "score", None)
                or _item_value(item, "fused_score", 0.0)
                or 0.0
            )
        except Exception:
            score = 0.0
        if score > best:
            best = score
    return best


def _normalize_context(result, items: list) -> str:
    context = str(_result_value(result, "context", "") or "").strip()
    if context:
        return context

    parts: list[str] = []
    for item in items:
        source_file = str(
            _item_value(item, "source", None)
            or _item_value(item, "source_file", "?")
            or "?"
        )
        page_start = _item_value(item, "page_start", None)
        page_suffix = f" p.{page_start}" if page_start is not None else ""
        text = str(_item_value(item, "text", "") or "").strip()
        if not text:
            continue
        parts.append(f"[source: {source_file}{page_suffix}]\n{text}")

    return "\n\n".join(parts).strip()


def _copy_source_into_workspace(*, source_path: str, workspace: Path, kb_name: str) -> Path | None:
    src = Path(source_path).expanduser()
    if not src.exists() or not src.is_file():
        return None

    dest_dir = Path(workspace) / "docs" / kb_name / "source"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    return dest


def _handle_kb_status(*, cfg, session) -> CommandResult:
    kb_name = _kb_name(cfg, session)
    return CommandResult(handled=True, text=f"KB attiva: {kb_name}")


def _handle_kb_list(*, cfg, workspace: Path) -> CommandResult:
    docs_root = Path(workspace) / "docs"
    names: list[str] = []
    if docs_root.exists():
        for item in sorted(docs_root.iterdir()):
            if item.is_dir():
                names.append(item.name)

    if not names:
        return CommandResult(handled=True, text="Nessuna KB disponibile.")

    return CommandResult(
        handled=True,
        text="KB disponibili:\n" + "\n".join(f"- {name}" for name in names),
    )


def _handle_kb_use(*, text: str, cfg, session) -> CommandResult:
    raw_name = text[len("/kb use "):].strip()
    if not raw_name:
        return CommandResult(handled=True, text="Uso: /kb use <name>")

    name = _sanitize_kb_name(raw_name)

    state = dict(session.get_state() or {})
    state["kb_name"] = name
    state["kb_enabled"] = True
    _persist_session_state(session, state)

    return CommandResult(
        handled=True,
        text=f"KB attiva impostata a: {name}",
    )


def _handle_kb_ingest(*, text: str, cfg, workspace: Path, session, ingest_fn) -> CommandResult:
    src = text[len("/kb ingest "):].strip()
    if not src:
        return CommandResult(handled=True, text="Uso: /kb ingest <path>")

    kb_name = _kb_name(cfg, session)

    copied_source = _copy_source_into_workspace(
        source_path=src,
        workspace=Path(workspace),
        kb_name=kb_name,
    )

    result = _call_ingest_kb_compat(
        ingest_fn=ingest_fn,
        kb_name=kb_name,
        source_path=src,
        cfg=cfg,
        workspace=Path(workspace),
    )

    state = dict(session.get_state() or {})
    state["kb_name"] = kb_name
    state["kb_enabled"] = True
    _persist_session_state(session, state)

    copied_source_path = _result_value(result, "copied_source_path", None) or (
        str(copied_source) if copied_source is not None else None
    )

    lines = [
        f"KB ingest completato [{kb_name}]",
        f"- source file copiato: {copied_source_path}",
        f"- source_files: {_result_value(result, 'source_files')}",
        f"- chunk_files: {_result_value(result, 'chunk_files')}",
        f"- indexed_points: {_result_value(result, 'indexed_points')}",
        f"- manifest: {_result_value(result, 'manifest_path')}",
    ]
    return CommandResult(handled=True, text="\n".join(lines))


def _handle_kb_query_local(*, text: str, cfg, workspace: Path, session, query_fn) -> CommandResult:
    query = text[len("/kb query "):].strip()
    if not query:
        return CommandResult(handled=True, text="Uso: /kb query <query>")

    kb_name = _kb_name(cfg, session)
    result = _call_query_kb_compat(
        query_fn=query_fn,
        kb_name=kb_name,
        query=query,
        workspace=Path(workspace),
    )

    items = _normalize_items(result)
    hits = _normalize_hits_count(result, items)
    max_score = _normalize_max_score(result, items)
    context = _normalize_context(result, items)

    lines = [
        f"KB query result [{kb_name}]",
        f"- query: {query}",
        f"- hits: {hits}",
        f"- max_score: {max_score:.4f}",
        "- top results:",
    ]

    for idx, item in enumerate(items, start=1):
        source_file = str(
            _item_value(item, "source", None)
            or _item_value(item, "source_file", "?")
            or "?"
        )
        page_start = _item_value(item, "page_start", None)
        source = f"{source_file} p.{page_start}" if page_start is not None else source_file
        score = float(
            _item_value(item, "score", None)
            or _item_value(item, "fused_score", 0.0)
            or 0.0
        )
        snippet = " ".join(str(_item_value(item, "text", "") or "").split())
        if len(snippet) > 180:
            snippet = snippet[:177] + "..."
        lines.append(f"  {idx}. {source} | score={score:.4f} | {snippet}")

    if context:
        lines.extend(["", "Context:", context])

    return CommandResult(handled=True, text="\n".join(lines))


def dispatch_kb_command(
    *,
    text: str,
    cfg,
    workspace: Path,
    session,
    ingest_fn,
    query_fn,
) -> CommandResult | None:
    raw = (text or "").strip()

    if raw == "/kb":
        return _handle_kb_status(cfg=cfg, session=session)

    if raw == "/kb list":
        return _handle_kb_list(cfg=cfg, workspace=Path(workspace))

    if raw.startswith("/kb use "):
        return _handle_kb_use(text=raw, cfg=cfg, session=session)

    if raw.startswith("/kb ingest "):
        return _handle_kb_ingest(
            text=raw,
            cfg=cfg,
            workspace=Path(workspace),
            session=session,
            ingest_fn=ingest_fn,
        )

    if raw == "/kb query":
        return CommandResult(handled=True, text="Uso: /kb query <query>")

    if raw.startswith("/kb query "):
        return _handle_kb_query_local(
            text=raw,
            cfg=cfg,
            workspace=Path(workspace),
            session=session,
            query_fn=query_fn,
        )

    if raw == "/kb ask":
        return CommandResult(handled=True, text="Uso: /kb ask <domanda>")

    if raw.startswith("/kb ask "):
        return None

    return None
