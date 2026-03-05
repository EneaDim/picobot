# kb_query

## Intent
Domande che richiedono risposte basate su documenti locali indicizzati nella knowledge base:
PDF, appunti, manuali, policy interne, note tecniche. L’utente vuole citazioni o riferimenti dal testo.

## Trigger words / patterns
- kb, knowledge base, documenti, documento, pdf, docs, doc
- “nel documento”, “in questo pdf”, “nelle note”, “nei file”
- “cerca”, “trova”, “dove dice”, “riporta”, “citazione”, “quote”

## Italiano: esempi realistici
- nel documento X cosa dice riguardo la retention?
- nel pdf che ho caricato, quali sono i requisiti?
- cerca nella kb: “sandbox runner”
- dove viene definito il router?
- puoi citarmi una parte in cui parla di tool sandbox?
- mi fai un riassunto basato SOLO sui documenti indicizzati?
- cosa dice la policy sul trattamento dati?
- nel file docs/architettura.pdf spiegami la sezione “config”

## English: examples
- in the document, what does it say about retention?
- search the knowledge base for “sandbox runner”
- where is the router defined?
- quote the part that mentions tool sandboxing
- answer using ONLY the indexed documents

## Follow-up stickiness examples
- ok, puoi dettagliare meglio?
- e questo come si applica?
- fammi un esempio pratico
- continua

## Negative examples
- ingest pdf ... (kb_ingest_pdf)
- news query (news_digest)
- youtube link (youtube_summarizer)
