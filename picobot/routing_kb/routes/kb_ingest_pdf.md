---
id: workflow:kb_ingest_pdf
kind: workflow
name: kb_ingest_pdf
title: Knowledge Base PDF Ingest
description: Importa o indicizza un PDF nella knowledge base locale attiva.
capabilities:
  - kb ingest
  - pdf import
  - document indexing
  - file ingestion
limitations:
  - non risponde a domande sul contenuto
  - richiede un file o un'azione esplicita di ingest
tags:
  - kb
  - ingest
  - pdf
  - import
  - index
example_queries:
  - /kb ingest docs/manuale.pdf
  - importa questo pdf nella kb
  - indicizza questo documento pdf
  - aggiungi questo file pdf alla knowledge base
requires_kb: false
requires_network: false
enabled: true
priority: 28
---

# kb_ingest_pdf

Usa questo workflow solo quando l'utente vuole:

- caricare un PDF nella knowledge base
- indicizzare un documento
- aggiungere un file alla KB
- importare un PDF per retrieval futuro

Non usarlo per:

- domande del tipo "nel documento..."
- domande sul contenuto della KB
- richieste di risposta grounded su documenti già ingestati
