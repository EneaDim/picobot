---
id: tool:sandbox_web
kind: tool
name: sandbox_web
title: Sandbox Web Fetch
description: Recupera il contenuto testuale di un URL tramite fetch sandboxato.
capabilities:
  - fetch url
  - text extraction
  - html cleaning
limitations:
  - richiede url esplicito
  - richiede rete
tags:
  - web
  - fetch
  - url
  - html
  - sandbox
example_queries:
  - scarica questa pagina https://example.com
  - recupera il testo di https://example.com
  - fetch this url https://example.com
  - tool sandbox_web {"url":"https://example.com"}
requires_kb: false
requires_network: true
enabled: true
priority: 60
---

# sandbox_web

Tool di fetch puntuale su URL specifici.
Non va confuso con news_digest, che fa search + fetch + sintesi.
