---
id: tool:web
kind: tool
name: web
title: Web
description: Recupera una pagina web con sandbox backend e ne estrae testo leggibile.
capabilities:
  - http
  - fetch
  - web
  - sandbox
limitations:
  - non fa ricerca multi-risultato
  - lavora su una URL alla volta
tags:
  - web
  - fetch
  - url
example_queries:
  - tool web {"url":"https://example.com"}
  - /fetch https://example.com
requires_kb: false
requires_network: true
enabled: true
priority: 88
---

# web

Usa questo tool quando l'utente vuole leggere il contenuto di una pagina web singola.

Preferiscilo per:
- fetch di una URL
- estrazione testo da pagina HTML
- lettura rapida di un articolo

Non usarlo per:
- ricerca web multi-risultato
- retrieval KB
- esecuzione codice Python
