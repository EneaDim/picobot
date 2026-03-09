from __future__ import annotations

import sys
from pathlib import Path
from textwrap import wrap


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_LEFT = 50
MARGIN_TOP = 790
MARGIN_BOTTOM = 60
LINE_HEIGHT = 14
LINES_PER_PAGE = int((MARGIN_TOP - MARGIN_BOTTOM) / LINE_HEIGHT)


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def chunk_pages(lines: list[str]) -> list[list[str]]:
    pages: list[list[str]] = []
    for i in range(0, len(lines), LINES_PER_PAGE):
        pages.append(lines[i:i + LINES_PER_PAGE])
    return pages or [[""]]


def build_page_stream(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 11 Tf"]
    y = MARGIN_TOP
    for line in lines:
        safe = pdf_escape(line)
        content_lines.append(f"1 0 0 1 {MARGIN_LEFT} {y} Tm ({safe}) Tj")
        y -= LINE_HEIGHT
    content_lines.append("ET")
    return "\n".join(content_lines).encode("latin-1", errors="replace")


def build_pdf(lines: list[str]) -> bytes:
    pages = chunk_pages(lines)
    objects: list[bytes] = []

    def add_object(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    # Placeholder ids built in order:
    # 1 catalog
    # 2 pages
    # then for each page: page obj, content obj
    # final font obj
    catalog_id = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")

    kids_refs = []
    page_object_ids = []
    content_object_ids = []

    add_object(b"<< /Type /Pages /Kids [] /Count 0 >>")  # placeholder pages obj

    for page_lines in pages:
        stream = build_page_stream(page_lines)
        page_obj_id = len(objects) + 1
        content_obj_id = len(objects) + 2

        page_object_ids.append(page_obj_id)
        content_object_ids.append(content_obj_id)
        kids_refs.append(f"{page_obj_id} 0 R")

        add_object(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 0 0 R >> >> /Contents {content_obj_id} 0 R >>".encode()
        )
        add_object(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    font_obj_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # Patch page objects with actual font ref
    for idx, page_obj_id in enumerate(page_object_ids):
        content_obj_id = content_object_ids[idx]
        objects[page_obj_id - 1] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_obj_id} 0 R >> >> /Contents {content_obj_id} 0 R >>".encode()
        )

    # Patch pages object
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids_refs)}] /Count {len(page_object_ids)} >>".encode()

    offsets = []
    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode())

    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode()
    )
    return bytes(out)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python scripts/make_test_pdf.py input.md output.pdf")
        return 2

    src = Path(sys.argv[1]).expanduser().resolve()
    dst = Path(sys.argv[2]).expanduser().resolve()

    text = src.read_text(encoding="utf-8", errors="replace")
    logical_lines: list[str] = []
    for raw in text.splitlines():
        raw = raw.rstrip()
        if not raw:
            logical_lines.append("")
            continue
        logical_lines.extend(wrap(raw, width=90) or [""])

    pdf = build_pdf(logical_lines)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(pdf)
    print(dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
