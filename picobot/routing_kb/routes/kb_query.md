---
id: workflow:kb_query
kind: workflow
name: kb_query
title: Knowledge Base Query
description: Risponde a domande grounded usando il contenuto della knowledge base attiva o di documenti già ingestati.
capabilities:
  - grounded qa
  - retrieval
  - document question answering
  - kb lookup
limitations:
  - richiede contenuto rilevante già presente nella kb
  - non importa nuovi documenti
tags:
  - kb
  - retrieval
  - document
  - grounded
  - context
example_queries:
  - cerca nella kb come funziona il router
  - nel documento, quali sono le tre primitive centrali del runtime?
  - nel documento, perché heartbeat non dovrebbe fare lavoro pesante direttamente?
  - nel documento, qual è il ruolo del ContextBuilder?
  - cosa dice il documento sul backend di ricerca web?
  - secondo la knowledge base, come funziona il message bus?
requires_kb: true
requires_network: false
enabled: true
priority: 96
---

# kb_query

Usa questo workflow quando l'utente vuole una risposta grounded basata su:

- documenti già ingestati
- knowledge base attiva
- testo presente nella KB
- domande del tipo "nel documento..."
- domande del tipo "cosa dice il testo..."
- domande del tipo "secondo la KB..."

Preferiscilo per:

- domande esplicite sul contenuto documentale
- spiegazioni basate su documenti locali
- recupero di fatti presenti nella knowledge base

Non usarlo per:

- importare PDF o nuovi documenti
- fare web search
- eseguire tool sandbox
