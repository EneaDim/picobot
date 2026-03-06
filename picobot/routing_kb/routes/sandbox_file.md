---
id: tool:sandbox_file
kind: tool
name: sandbox_file
title: Sandbox File
description: Lettura o preview di file e directory locali all'interno dei limiti consentiti della sandbox.
capabilities:
  - file preview
  - file read
  - directory listing
limitations:
  - richiede path esplicito
  - limitato alla root consentita
tags:
  - file
  - preview
  - directory
  - sandbox
example_queries:
  - apri il file README.md
  - mostrami il contenuto di ./docs/notes.txt
  - lista la directory ./docs
  - tool sandbox_file {"root":".","path":"README.md"}
requires_kb: false
requires_network: false
enabled: true
priority: 65
---

# sandbox_file

Tool sandboxato per operazioni locali sui file. Non sostituisce la KB query,
che invece lavora su documenti già indicizzati.
