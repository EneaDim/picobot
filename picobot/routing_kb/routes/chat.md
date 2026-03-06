---
id: workflow:chat
kind: workflow
name: chat
title: General Chat
description: Conversazione generale, spiegazioni, brainstorming, traduzioni, riscrittura e fallback quando nessun tool o workflow specifico è chiaramente appropriato.
capabilities:
  - conversazione generale
  - spiegazioni
  - brainstorming
  - traduzione
  - riscrittura
  - fallback
limitations:
  - non grounded sui documenti locali
  - non esegue tool
  - non produce retrieval documentale
tags:
  - chat
  - conversation
  - fallback
  - explanation
  - rewrite
  - translate
example_queries:
  - ciao come va?
  - spiegami cos’è un agent locale
  - riscrivi questo testo in modo più chiaro
  - traduci in inglese questo paragrafo
  - dammi idee per un progetto python
requires_kb: false
requires_network: false
enabled: true
priority: 10
---

# chat

Route di fallback per richieste generiche o non chiaramente classificabili
come tool, workflow esterni, retrieval documentale o digest news.
