from __future__ import annotations

# Questo file contiene gli oggetti dati del router.
#
# Obiettivo:
# - strutture semplici
# - responsabilità chiare
# - niente oggetti "furbi"
# - facile serializzazione e debug
#
# Nota:
# Il router deve decidere tra:
# - chat
# - workflow
# - tool
#
# Il record di base è RouteRecord, che nasce dai file markdown
# presenti in picobot/knowledge/routing_kb/routes/.
from dataclasses import dataclass, field
from typing import Any, Literal

# Tipi di record ammessi dal router.
RouteKind = Literal["tool", "workflow", "agent"]

# Azioni finali del router.
RouteAction = Literal["chat", "tool", "workflow"]


@dataclass(frozen=True)
class RouteRecord:
    """
    Documento canonico di routing.

    Questo oggetto rappresenta una route "descritta" e indicizzata.
    Arriva dai file markdown e diventa il vero input del router retriever.

    Campi importanti:
    - id: identificatore stabile, es. "workflow:news_digest"
    - kind: tipo logico della route
    - name: nome dispatchabile usato dall'orchestrator o tool registry
    - title: titolo umano leggibile
    - description: descrizione breve
    - capabilities: cosa sa fare
    - limitations: cosa NON sa fare / vincoli
    - tags: segnali semantici compatti
    - example_queries: esempi realistici di richieste utente
    - requires_kb: se serve KB attiva
    - requires_network: se serve rete
    - enabled: flag per spegnere route senza cancellare doc
    - priority: piccolo bias ordinabile, non dominante
    - metadata: campo estendibile per il futuro
    """

    id: str
    kind: RouteKind
    name: str
    title: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    example_queries: list[str] = field(default_factory=list)
    requires_kb: bool = False
    requires_network: bool = False
    enabled: bool = True
    priority: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """
        Converte il record nel payload serializzabile per Qdrant.
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "limitations": list(self.limitations),
            "tags": list(self.tags),
            "example_queries": list(self.example_queries),
            "requires_kb": self.requires_kb,
            "requires_network": self.requires_network,
            "enabled": self.enabled,
            "priority": self.priority,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RouteRecord":
        """
        Ricostruisce un record da payload serializzato.
        """
        return cls(
            id=str(payload.get("id") or ""),
            kind=str(payload.get("kind") or "workflow"),
            name=str(payload.get("name") or ""),
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            capabilities=list(payload.get("capabilities") or []),
            limitations=list(payload.get("limitations") or []),
            tags=list(payload.get("tags") or []),
            example_queries=list(payload.get("example_queries") or []),
            requires_kb=bool(payload.get("requires_kb", False)),
            requires_network=bool(payload.get("requires_network", False)),
            enabled=bool(payload.get("enabled", True)),
            priority=int(payload.get("priority", 50)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RouteCandidate:
    """
    Candidato prodotto dal router retriever.

    Conserviamo:
    - record: il record sorgente
    - vector_score: score semantico
    - lexical_score: score BM25 normalizzato
    - rerank_score: lasciato per futuro uso opzionale
    - final_score: score finale usato per ordinare
    - reason: stringa debug leggibile
    """
    record: RouteRecord
    vector_score: float
    lexical_score: float
    rerank_score: float
    final_score: float
    reason: str


@dataclass(frozen=True)
class SessionRouteContext:
    """
    Contesto minimo utile al router.

    Il router non deve conoscere la sessione intera.
    Gli basta sapere:
    - se c'è una KB attiva
    - come si chiama
    - se la KB è abilitata
    - lingua di input
    """
    kb_name: str = ""
    kb_enabled: bool = True
    has_kb: bool = False
    input_lang: str = "it"


@dataclass(frozen=True)
class RouteDecision:
    """
    Decisione finale prodotta dal router.

    Convenzione:
    - action="chat"   => fallback conversazionale
    - action="tool"   => dispatch tool diretto
    - action="workflow" => dispatch workflow

    name:
    - per tool: nome tool
    - per workflow: nome workflow
    - per chat: "chat"

    args:
    - popolato solo quando il router produce argomenti espliciti
      (es. tool esplicito o slash command già normalizzato)
    """
    action: RouteAction
    name: str
    reason: str
    args: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    candidates: list[RouteCandidate] = field(default_factory=list)
