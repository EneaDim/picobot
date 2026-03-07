from __future__ import annotations

# Questo file gestisce il caricamento del corpus router dal filesystem.
#
# Source of truth:
# - picobot/routing_kb/routes/*.md
#
# Qui NON c'è logica di scoring.
# Qui facciamo solo:
# - discover dei file
# - parse dei markdown
# - validazione minima
# - ordinamento stabile
from pathlib import Path

from picobot.router.documents import load_route_document, route_record_from_document
from picobot.router.schemas import RouteRecord


def router_docs_dir() -> Path:
    """
    Restituisce la directory dei documenti di routing.
    """
    return (Path(__file__).resolve().parent.parent / "routing_kb" / "routes").resolve()


def route_doc_paths() -> list[Path]:
    """
    Elenca i file markdown usati come source of truth del router.
    """
    root = router_docs_dir()
    root.mkdir(parents=True, exist_ok=True)

    return sorted([p for p in root.glob("*.md") if p.is_file()])


def load_router_records() -> list[RouteRecord]:
    """
    Carica tutti i RouteRecord dal corpus markdown.
    """
    records: list[RouteRecord] = []
    seen_ids: set[str] = set()
    seen_names: set[tuple[str, str]] = set()

    for path in route_doc_paths():
        doc = load_route_document(path)
        record = route_record_from_document(doc)

        # Unicità dell'ID.
        if record.id in seen_ids:
            raise ValueError(f"duplicate router id: {record.id} ({path})")

        # Unicità ragionevole di (kind, name).
        pair = (record.kind, record.name)
        if pair in seen_names:
            raise ValueError(f"duplicate router kind/name: {pair} ({path})")

        seen_ids.add(record.id)
        seen_names.add(pair)

        records.append(record)

    # Ordinamento stabile:
    # - prima priority discendente
    # - poi id crescente
    records.sort(key=lambda r: (-int(r.priority), r.id))
    return records
