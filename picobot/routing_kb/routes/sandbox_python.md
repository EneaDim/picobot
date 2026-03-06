---
id: tool:sandbox_python
kind: tool
name: sandbox_python
title: Sandbox Python
description: Esegue codice Python in sandbox per calcoli, parsing, snippet e piccoli esperimenti deterministici.
capabilities:
  - python execution
  - math
  - parsing
  - small scripts
limitations:
  - richiede codice esplicito
  - non è una chat di coding generica
tags:
  - python
  - sandbox
  - code
  - execute
example_queries:
  - esegui questo python print(2+2)
  - run python for i in range(3): print(i)
  - calcola con python questo snippet
  - tool sandbox_python {"code":"print(2+2)"}
requires_kb: false
requires_network: false
enabled: true
priority: 75
---

# sandbox_python

Tool sandboxato per esecuzione di codice Python esplicito.
Va scelto quando l’utente vuole davvero far girare codice.
