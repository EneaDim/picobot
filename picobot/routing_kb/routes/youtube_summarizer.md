---
id: workflow:youtube_summarizer
kind: workflow
name: youtube_summarizer
title: YouTube Summarizer
description: Riassume un video YouTube usando transcript o metadata e produce una sintesi strutturata.
capabilities:
  - youtube transcript
  - video summary
  - captions extraction
limitations:
  - dipende da transcript o metadata disponibili
tags:
  - youtube
  - video
  - transcript
  - summary
example_queries:
  - riassumi questo video https://www.youtube.com/watch?v=ssYt09bCgUY
  - fammi il riassunto del video youtube https://youtu.be/ssYt09bCgUY
  - get transcript and summarize it
  - key takeaways from this youtube video https://youtu.be/ssYt09bCgUY
requires_kb: false
requires_network: false
enabled: true
priority: 95
---

# youtube_summarizer

Workflow specifico per YouTube. La presenza di un URL YouTube è un forte
segnale esplicito e deve vincere facilmente nel routing.
