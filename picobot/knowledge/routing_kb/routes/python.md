---
id: tool:python
kind: tool
name: python
title: Python
description: Esegue codice Python in sandbox locale o docker persistente.
capabilities:
  - python
  - code
  - sandbox
  - exec
limitations:
  - non è pensato per processi lunghi
  - non è pensato per networking arbitrario
tags:
  - python
  - code
  - sandbox
example_queries:
  - tool python {"code":"print(2+2)"}
  - /py print(2+2)
requires_kb: false
requires_network: false
enabled: true
priority: 92
---

# python

Usa questo tool quando l'utente vuole eseguire codice Python in sandbox.

Preferiscilo per:
- piccoli script
- test rapidi
- parsing o trasformazioni locali
- codice non persistente

Non usarlo per:
- retrieval documentale
- fetch web
- lettura file semplice
