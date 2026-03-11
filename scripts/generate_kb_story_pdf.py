from __future__ import annotations

import textwrap
from pathlib import Path


TITLE = "Project Glass Orchard — dossier narrativo per test KB"

SECTIONS: list[tuple[str, list[str]]] = [
    (
        "1. Premessa",
        [
            "Nel marzo 2023 la biologa computazionale Livia Serra ricevette un archivio cifrato da Arturo Venn, ex cartografo industriale della società Northwake Signals.",
            "L'archivio conteneva note, mappe e trascrizioni relative a un progetto interno chiamato Glass Orchard.",
            "Secondo le note iniziali, Glass Orchard non era un prodotto commerciale ma un programma di osservazione territoriale pensato per studiare micro-ecosistemi urbani attraverso sensori ottici e sonici.",
        ],
    ),
    (
        "2. Personaggi chiave",
        [
            "Livia Serra è la protagonista principale del dossier. Nata a Parma, lavora tra Milano e Trieste e ha una formazione mista in bioinformatica e sistemi distribuiti.",
            "Arturo Venn è descritto come riservato, metodico e quasi ossessionato dalle nomenclature. Nei documenti interni usa spesso l'alias A. Venn oppure la sigla AV-17.",
            "Mira Koenig è la responsabile delle operazioni sul campo. Coordina i team locali e firma le checklist con la sigla MK.",
            "Jonas Reed è il referente sicurezza del programma. In un memo del 14 aprile 2023 insiste sul fatto che il nodo Delta-Red non deve mai essere sincronizzato durante le finestre di manutenzione.",
        ],
    ),
    (
        "3. Luoghi",
        [
            "I luoghi principali citati sono quattro: Serra Vetro a Trieste, il deposito Old Quarry vicino a Gorizia, il laboratorio Faro-3 a Ravenna e il padiglione Echo Basin alla periferia di Lubiana.",
            "Serra Vetro non è una serra agricola tradizionale ma un ex vivaio riadattato a centro di calibrazione sensori.",
            "Old Quarry è importante perché ospita la camera fredda dove venivano conservati i moduli Prisma-4 prima della distribuzione.",
            "Faro-3 compare nei documenti come sito di verifica firmware, mentre Echo Basin è usato per simulazioni acustiche notturne.",
        ],
    ),
    (
        "4. Oggetti e componenti",
        [
            "I componenti più importanti sono il sensore Prisma-4, il modulo di sincronizzazione Lantern, il pacco batterie Morrow e il relay a bassa potenza Delta-Red.",
            "Prisma-4 è ottimizzato per luce diffusa e superfici riflettenti. In più pagine viene specificato che non è affidabile sotto pioggia intensa.",
            "Lantern è il componente usato per riallineare i timestamp tra i nodi remoti. Arturo Venn lo definisce il metronomo del sistema.",
            "Morrow è un pacco batterie sperimentale, leggero ma instabile oltre i 34 gradi.",
            "Delta-Red non è un sensore ma un relay di coordinamento usato nelle finestre di handoff tra cluster.",
        ],
    ),
    (
        "5. Timeline operativa",
        [
            "Il 12 marzo 2023 Livia Serra riceve il primo archivio parziale.",
            "Il 14 aprile 2023 Jonas Reed invia il memo di sicurezza sul nodo Delta-Red.",
            "Il 2 maggio 2023 Mira Koenig autorizza una prova notturna a Echo Basin con tre unità Prisma-4 e due moduli Lantern.",
            "Il 18 maggio 2023 una nota interna segnala che il pacco Morrow si degrada più rapidamente del previsto nel sito Faro-3.",
            "Il 7 giugno 2023 Arturo Venn consegna a Livia una mappa annotata a mano con il percorso Serra Vetro -> Old Quarry -> Echo Basin.",
            "Il 21 giugno 2023 il test di sincronizzazione viene sospeso perché un relay Delta-Red entra in stato incoerente dopo una finestra di manutenzione non autorizzata.",
        ],
    ),
    (
        "6. Incidenti e anomalie",
        [
            "L'anomalia più citata è chiamata river ghosting: un riflesso multiplo che altera la lettura di Prisma-4 vicino a superfici bagnate o vetrate.",
            "Una seconda anomalia, chiamata lantern drift, si verifica quando i moduli Lantern perdono allineamento dopo lunghi periodi senza ricalibrazione.",
            "Il dossier precisa che river ghosting e lantern drift sono problemi distinti e non devono essere confusi.",
            "In un allegato tecnico si specifica che il river ghosting è stato osservato soprattutto nel sito Serra Vetro, mentre il lantern drift è stato riprodotto più volte a Echo Basin.",
        ],
    ),
    (
        "7. Regole operative",
        [
            "Mai sincronizzare Delta-Red durante manutenzione attiva.",
            "Mai usare Morrow oltre i 34 gradi ambiente.",
            "Se Prisma-4 opera vicino a vetrate bagnate, marcare i risultati come potenzialmente affetti da river ghosting.",
            "Ogni sessione notturna a Echo Basin deve includere almeno un controllo Lantern prima e dopo il test.",
        ],
    ),
    (
        "8. Dettagli volutamente facili da confondere",
        [
            "Serra Vetro è a Trieste, non a Ravenna.",
            "Faro-3 è a Ravenna, non a Lubiana.",
            "Mira Koenig autorizza la prova del 2 maggio 2023; Jonas Reed scrive invece il memo del 14 aprile 2023.",
            "Delta-Red non è un sensore ottico, mentre Prisma-4 sì.",
            "Lantern serve per la sincronizzazione dei timestamp, non per la misura ambientale diretta.",
        ],
    ),
    (
        "9. Chiusura",
        [
            "Livia Serra conclude che Glass Orchard non era solo un esperimento ambientale, ma anche un test di governance tecnica: i documenti mostrano che i problemi più gravi nascevano dai passaggi di coordinamento tra persone, siti e procedure.",
            "La frase finale del dossier è: il sistema falliva meno per i sensori e più per le eccezioni non dichiarate.",
        ],
    ),
]


def escape_pdf_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_lines() -> list[str]:
    lines: list[str] = []
    lines.append(TITLE)
    lines.append("")
    for title, paragraphs in SECTIONS:
        lines.append(title)
        lines.append("")
        for p in paragraphs:
            wrapped = textwrap.wrap(p, width=88)
            if not wrapped:
                lines.append("")
            else:
                lines.extend(wrapped)
            lines.append("")
    return lines


def paginate(lines: list[str], lines_per_page: int = 42) -> list[list[str]]:
    pages: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        cur.append(line)
        if len(cur) >= lines_per_page:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    return pages


def pdf_stream_for_page(lines: list[str], page_no: int, total_pages: int) -> bytes:
    y = 800
    parts = ["BT", "/F1 12 Tf", "50 800 Td", "14 TL"]
    for idx, line in enumerate(lines):
        if idx == 0 and page_no == 1:
            parts.append("/F1 18 Tf")
            parts.append(f"({escape_pdf_text(line)}) Tj")
            parts.append("/F1 12 Tf")
        else:
            parts.append(f"({escape_pdf_text(line)}) Tj")
        parts.append("T*")
        y -= 14

    parts.append("T*")
    parts.append(f"(Pagina {page_no} di {total_pages}) Tj")
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1", errors="replace")
    return stream


def build_pdf_bytes() -> bytes:
    pages = paginate(build_lines())
    objects: list[bytes] = []

    def add_object(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    font_obj = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    content_ids: list[int] = []

    placeholder_pages_obj_index = len(objects) + 1

    for page_no, page_lines in enumerate(pages, start=1):
        stream = pdf_stream_for_page(page_lines, page_no, len(pages))
        content_obj = add_object(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        )
        content_ids.append(content_obj)

        page_obj = add_object(
            (
                f"<< /Type /Page /Parent {placeholder_pages_obj_index} 0 R "
                f"/MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
                f"/Contents {content_obj} 0 R >>"
            ).encode("ascii")
        )
        page_ids.append(page_obj)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_obj = add_object(
        f"<< /Type /Pages /Count {len(page_ids)} /Kids [ {kids} ] >>".encode("ascii")
    )

    catalog_obj = add_object(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode("ascii"))

    xref_positions: list[int] = []
    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    for idx, obj in enumerate(objects, start=1):
        xref_positions.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_start = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for pos in xref_positions:
        out.extend(f"{pos:010d} 00000 n \n".encode("ascii"))

    out.extend(
        (
            f"trailer\n<< /Size {len(objects)+1} /Root {catalog_obj} 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def main() -> None:
    out_dir = Path("testdata/kb")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "glass_orchard_story.pdf"
    out_path.write_bytes(build_pdf_bytes())
    print(out_path)


if __name__ == "__main__":
    main()
