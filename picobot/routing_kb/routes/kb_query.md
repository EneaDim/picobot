---
id: workflow:kb_query
kind: workflow
name: kb_query
title: Knowledge Base Query
description: Domande che devono essere risolte usando documenti locali già indicizzati nella knowledge base, con grounding documentale.
capabilities:
  - document qa
  - retrieval grounded answers
  - lookup su pdf e documenti tecnici
  - citazioni da documenti locali
limitations:
  - richiede kb attiva
  - risponde solo con ciò che è recuperabile nei documenti indicizzati
tags:
  - kb
  - rag
  - documents
  - pdf
  - local docs
  - retrieval
example_queries:
  - nel documento cosa dice riguardo la retention?
  - cerca nella kb sandbox runner
  - dove viene definito il router?
  - mi fai un riassunto basato solo sui documenti indicizzati?
  - cosa dice la policy sul trattamento dati?
requires_kb: true
requires_network: false
enabled: true
priority: 92
---

# kb_query

Questa route è per query documentali grounded sulla KB locale.

Va distinta da:
- ingest di nuovi pdf
- news sul web
- tool sandbox espliciti
- chat generale
