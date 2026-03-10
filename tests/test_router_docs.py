from pathlib import Path

from picobot.routing.documents import load_route_document, route_record_from_document


def test_all_route_docs_have_required_fields():
    root = Path("picobot/knowledge/routing_kb/routes")
    assert root.exists()

    docs = sorted(root.glob("*.md"))
    assert docs, "no route docs found"

    for path in docs:
        doc = load_route_document(path)
        record = route_record_from_document(doc)
        assert record.id
        assert record.name
        assert record.kind
        assert record.title
