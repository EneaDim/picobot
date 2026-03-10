---
id: tool:tts
kind: tool
name: tts
title: Text To Speech
description: Converte testo in audio usando un backend text-to-speech locale configurato.
capabilities:
  - text to speech
  - speech synthesis
  - voice output
limitations:
  - richiede testo esplicito
  - dipende dal backend TTS locale installato
tags:
  - tts
  - speech
  - audio
  - piper
  - synthesis
example_queries:
  - converti questo testo in audio
  - genera una voce da questo testo
  - tool tts {"text":"ciao mondo","lang":"it"}
requires_kb: false
requires_network: false
enabled: true
priority: 62
---

# tts

Tool per generare audio da testo.
È pensato per essere riusabile da sub-agent, Telegram e pipeline podcast.
