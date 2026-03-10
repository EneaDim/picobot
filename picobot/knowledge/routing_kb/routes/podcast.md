---
id: workflow:podcast
kind: workflow
name: podcast
title: Podcast Generator
description: Genera un copione podcast e, se configurato, produce audio locale tramite TTS.
capabilities:
  - podcast script
  - audio summary
  - spoken content generation
limitations:
  - richiede richiesta esplicita di podcast o audio
tags:
  - podcast
  - audio
  - tts
  - spoken summary
example_queries:
  - crea un podcast su sandboxing tools
  - fammi un episodio audio su ai regulation
  - podcast: intelligenza artificiale e europa
  - voglio ascoltare un riassunto audio
requires_kb: false
requires_network: false
enabled: true
priority: 70
---

# podcast

Route dedicata a output audio o podcast-style. Non va confusa con il
news digest testuale o con la chat generica.
