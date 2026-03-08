from __future__ import annotations

import sys
from pathlib import Path
from textwrap import wrap


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(lines: list[str]) -> bytes:
    page_width = 595
    page_height = 842
    margin_left = 50
    margin_top = 790
    line_height = 14

    content_lines = ["BT", "/F1 11 Tf"]
    y = margin_top
    for line in lines:
        if y < 60:
            break
        safe = pdf_escape(line)
        content_lines.append(f"1 0 0 1 {margin_left} {y} Tm ({safe}) Tj")
        y -= line_height
    content_lines.append("ET")
    content_stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = []

    def add_object(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    obj1 = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    obj2 = add_object(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    obj3 = add_object(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".encode()
    )
    obj4 = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    obj5 = add_object(
        b"<< /Length " + str(len(content_stream)).encode() + b" >>\nstream\n" + content_stream + b"\nendstream"
    )

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
            f"trailer\n<< /Size {len(objects) + 1} /Root {obj1} 0 R >>\n"
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
