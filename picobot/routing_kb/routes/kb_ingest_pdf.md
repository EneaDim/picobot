---
id: workflow:kb_ingest_pdf
kind: workflow
name: kb_ingest_pdf
title: Knowledge Base PDF Ingest
description: Ingest o indicizzazione di un PDF nella knowledge base locale. È un'azione di caricamento, non una query sul contenuto.
capabilities:
  - ingest pdf
  - indicizzazione documento
  - aggiunta documento alla kb
limitations:
  - non risponde al contenuto del documento
  - richiede path o riferimento a file pdf
tags:
  - kb
  - ingest
  - pdf
  - document
  - index
example_queries:
  - ingest pdf ./docs/manuale.pdf
  - indicizza pdf ./contratto.pdf
  - aggiungi questo pdf alla kb ./docs/report.pdf
  - importa documento ./docs/policy.pdf
  - /kb ingest ./docs/architettura.pdf
requires_kb: false
requires_network: false
enabled: true
priority: 85
---

# kb_ingest_pdf

Questa route va scelta quando l’utente vuole caricare o indicizzare un PDF
nella knowledge base locale, non quando vuole chiedere cosa contiene.
