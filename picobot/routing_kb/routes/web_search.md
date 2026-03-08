---
id: tool:web_search
kind: tool
name: web_search
title: Web Search
description: Ricerca sul web tramite backend locale di search per trovare fonti, pagine o risultati da elaborare.
capabilities:
  - web search
  - source discovery
  - search results
limitations:
  - non produce digest completo da solo
  - richiede rete
tags:
  - web
  - search
  - sources
example_queries:
  - cerca sul web verilator tracing docs
  - search the web for local rag architecture
  - tool web_search {"query":"verilator","count":3}
requires_kb: false
requires_network: true
enabled: true
priority: 68
---

# web_search

Tool di ricerca web puro. È diverso da news_digest, che costruisce una
rassegna o sintesi multi-fonte.

Il backend concreto è un dettaglio infrastrutturale e non deve emergere
nel runtime o nei messaggi verso l'utente.
