---
id: tool:file
kind: tool
name: file
title: File
description: Legge file o lista directory dentro il workspace sandboxato.
capabilities:
  - filesystem
  - file
  - sandbox
  - read
limitations:
  - non scarica URL
  - non esegue codice
tags:
  - file
  - filesystem
  - workspace
example_queries:
  - tool file {"root":".","path":"README.md"}
  - /file README.md
requires_kb: false
requires_network: false
enabled: true
priority: 90
---

# file

Usa questo tool quando l'utente vuole leggere un file o esplorare una directory nel workspace.

Preferiscilo per:
- README
- output generati
- file di configurazione
- listare cartelle

Non usarlo per:
- fetch di URL
- esecuzione codice Python
- KB retrieval
