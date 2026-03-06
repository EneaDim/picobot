---
id: tool:stt
kind: tool
name: stt
title: Speech To Text
description: Trascrive un file audio locale in testo usando un backend speech-to-text locale configurato.
capabilities:
  - speech to text
  - transcription
  - audio to text
limitations:
  - richiede un file audio locale esplicito
  - dipende dal backend STT locale installato
tags:
  - stt
  - speech
  - transcription
  - audio
  - whisper
example_queries:
  - trascrivi questo file audio
  - converti audio in testo
  - tool stt {"audio_path":"./audio.wav","lang":"it"}
requires_kb: false
requires_network: false
enabled: true
priority: 62
---

# stt

Tool per trasformare audio locale in testo.
È utile per voice note, audio file e pipeline vocali di sub-agent.
