from __future__ import annotations

from picobot.router.schemas import RouteRecord


def router_doc_text(doc: RouteRecord) -> str:
    parts = [
        f"TITLE: {doc.title}",
        f"NAME: {doc.name}",
        f"KIND: {doc.kind}",
        f"DESCRIPTION: {doc.description}",
        f"CAPABILITIES: {'; '.join(doc.capabilities)}" if doc.capabilities else "",
        f"LIMITATIONS: {'; '.join(doc.limitations)}" if doc.limitations else "",
        f"TAGS: {'; '.join(doc.tags)}" if doc.tags else "",
        f"EXAMPLES: {'; '.join(doc.example_queries)}" if doc.example_queries else "",
        f"REQUIRES_KB: {doc.requires_kb}",
        f"REQUIRES_NETWORK: {doc.requires_network}",
        f"PRIORITY: {doc.priority}",
    ]
    return "\n".join([p for p in parts if p]).strip()
