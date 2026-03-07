from __future__ import annotations

# Parser robusto dei route documents markdown.
#
# Source of truth:
# - picobot/routing_kb/routes/*.md
#
# Formato atteso:
#
# ---
# id: workflow:chat
# kind: workflow
# name: chat
# title: General Chat
# description: ...
# capabilities:
#   - ...
#   - ...
# ---
# body markdown...
#
# Obiettivi:
# - parser semplice ma robusto
# - niente dipendenza PyYAML
# - errori chiari e localizzati
# - frontmatter sempre separato bene dal body
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from picobot.router.schemas import RouteRecord


@dataclass(frozen=True)
class RouteDocument:
    """
    Documento markdown grezzo caricato dal filesystem.
    """
    path: Path
    frontmatter: dict[str, Any]
    body: str


def _parse_scalar(raw: str) -> Any:
    """
    Parser scalar minimale.

    Supporta:
    - true / false
    - interi
    - stringhe quoted
    - stringhe plain
    """
    value = (raw or "").strip()

    if value == "":
        return ""

    low = value.lower()

    if low == "true":
        return True

    if low == "false":
        return False

    if value.isdigit():
        try:
            return int(value)
        except Exception:
            pass

    if value.startswith("-") and value[1:].isdigit():
        try:
            return int(value)
        except Exception:
            pass

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]

    return value


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """
    Estrae le righe del frontmatter e il body markdown.

    Regole:
    - il file deve iniziare con una riga che contiene solo ---
    - il frontmatter termina alla successiva riga che contiene solo ---
    - tutto il resto è body

    Questo approccio è più robusto di cercare '\n---\n' con find().
    """
    src = text or ""
    lines = src.splitlines()

    if not lines:
        return [], ""

    # Deve partire con frontmatter marker.
    if lines[0].strip() != "---":
        return [], src

    end_idx: int | None = None

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx is None:
        # Frontmatter mal chiuso: trattiamo tutto come body.
        return [], src

    header_lines = lines[1:end_idx]
    body_lines = lines[end_idx + 1 :]

    body = "\n".join(body_lines).strip()
    return header_lines, body


def _parse_frontmatter_lines(lines: list[str]) -> dict[str, Any]:
    """
    Interpreta le righe del frontmatter.

    Supporta:
    - key: value
    - key:
        - item1
        - item2
    """
    data: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip()

        if not line.strip():
            continue

        if line.lstrip().startswith("#"):
            continue

        stripped = line.strip()

        # Item di lista.
        if stripped.startswith("- "):
            if current_list_key is None:
                continue
            data.setdefault(current_list_key, [])
            if not isinstance(data[current_list_key], list):
                data[current_list_key] = []
            data[current_list_key].append(_parse_scalar(stripped[2:]))
            continue

        # Riga key: value
        if ":" not in line:
            current_list_key = None
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        if not key:
            current_list_key = None
            continue

        # key:   -> apertura lista o campo vuoto
        if value == "":
            data[key] = []
            current_list_key = key
            continue

        data[key] = _parse_scalar(value)
        current_list_key = None

    return data


def load_route_document(path: Path) -> RouteDocument:
    """
    Carica un documento markdown di routing dal filesystem.
    """
    file_path = Path(path).resolve()
    text = file_path.read_text(encoding="utf-8")

    header_lines, body = _split_frontmatter(text)
    frontmatter = _parse_frontmatter_lines(header_lines) if header_lines else {}

    return RouteDocument(
        path=file_path,
        frontmatter=frontmatter,
        body=body,
    )


def _required_str(data: dict[str, Any], key: str, *, path: Path | None = None) -> str:
    """
    Estrae una stringa obbligatoria dal frontmatter.
    """
    value = str(data.get(key) or "").strip()
    if value:
        return value

    where = f" in {path}" if path is not None else ""
    raise ValueError(f"missing required field '{key}'{where}")


def _list_of_str(data: dict[str, Any], key: str) -> list[str]:
    """
    Estrae una lista di stringhe, tollerando sia lista sia stringa singola.
    """
    raw = data.get(key)

    if raw is None:
        return []

    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]

    value = str(raw).strip()
    return [value] if value else []


def route_record_from_document(doc: RouteDocument) -> RouteRecord:
    """
    Converte un documento markdown in RouteRecord validato.
    """
    fm = dict(doc.frontmatter or {})

    route_id = _required_str(fm, "id", path=doc.path)
    kind = _required_str(fm, "kind", path=doc.path)
    name = _required_str(fm, "name", path=doc.path)
    title = _required_str(fm, "title", path=doc.path)

    description = str(fm.get("description") or "").strip()
    if not description:
        description = (doc.body.split("\n\n", 1)[0] if doc.body else "").strip()

    return RouteRecord(
        id=route_id,
        kind=str(kind),
        name=name,
        title=title,
        description=description,
        capabilities=_list_of_str(fm, "capabilities"),
        limitations=_list_of_str(fm, "limitations"),
        tags=_list_of_str(fm, "tags"),
        example_queries=_list_of_str(fm, "example_queries"),
        requires_kb=bool(fm.get("requires_kb", False)),
        requires_network=bool(fm.get("requires_network", False)),
        enabled=bool(fm.get("enabled", True)),
        priority=int(fm.get("priority", 50)),
        metadata={
            "source_path": str(doc.path),
            "body_markdown": doc.body,
        },
    )


def router_doc_text(record: RouteRecord) -> str:
    """
    Costruisce il testo canonico da indicizzare semanticamente.
    """
    parts: list[str] = []

    parts.append(f"TITLE: {record.title}")
    parts.append(f"NAME: {record.name}")
    parts.append(f"KIND: {record.kind}")
    parts.append(f"DESCRIPTION: {record.description}")

    if record.capabilities:
        parts.append("CAPABILITIES: " + "; ".join(record.capabilities))

    if record.limitations:
        parts.append("LIMITATIONS: " + "; ".join(record.limitations))

    if record.tags:
        parts.append("TAGS: " + "; ".join(record.tags))

    if record.example_queries:
        parts.append("EXAMPLE_QUERIES: " + " || ".join(record.example_queries))

    parts.append(f"REQUIRES_KB: {record.requires_kb}")
    parts.append(f"REQUIRES_NETWORK: {record.requires_network}")
    parts.append(f"PRIORITY: {record.priority}")

    body = str(record.metadata.get("body_markdown") or "").strip()
    if body:
        parts.append("BODY: " + body)

    return "\n".join(parts).strip()


def router_records_fingerprint(records: list[RouteRecord]) -> str:
    """
    Produce un fingerprint stabile del corpus router.
    """
    lines: list[str] = []

    for rec in sorted(records, key=lambda x: x.id):
        lines.append(rec.id)
        lines.append(rec.kind)
        lines.append(rec.name)
        lines.append(rec.title)
        lines.append(rec.description)
        lines.extend(rec.capabilities)
        lines.extend(rec.limitations)
        lines.extend(rec.tags)
        lines.extend(rec.example_queries)
        lines.append(str(rec.requires_kb))
        lines.append(str(rec.requires_network))
        lines.append(str(rec.enabled))
        lines.append(str(rec.priority))

    blob = "\n".join(lines).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()
