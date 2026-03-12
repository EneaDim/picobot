# Picobot — feature flows con esempi pratici

Questo documento descrive il flusso reale di ogni feature principale, con esempi di input e comportamento atteso.

---

## 1. Chat normale

### Input
Ciao, puoi spiegarmi a cosa serve questo progetto?

### Flusso
1. CLI o Telegram invia `inbound.text`
2. Runtime apre il turno
3. Router valuta la route
4. Se non ci sono segnali forti per KB/tool/workflow specifici, seleziona `chat`
5. Context builder prepara memoria + history
6. Provider `chat` genera la risposta
7. Runtime pubblica `outbound.text`

### Atteso
- status visibili per fase
- route `chat`
- risposta testuale finale

---

## 2. KB ingest esplicito

### Input
/kb ingest tests/fixtures/data/kb/glass_orchard_story.pdf

### Flusso
1. Comando gestito localmente dalla CLI
2. Ingest PDF
3. Parsing testo
4. Chunking
5. Indicizzazione lessicale
6. Embedding locale
7. Persistenza KB

### Atteso
- ingest deterministico
- PDF disponibile nella KB selezionata
- nessun passaggio LLM necessario per l’ingest

---

## 3. KB query raw deterministica

### Input
/kb query Dove si trova Serra Vetro?

### Flusso
1. Comando locale
2. Query diretta sulla KB attiva
3. Risultato raw dal retrieval layer
4. Nessuna answer generativa richiesta

### Atteso
- comportamento stabile e deterministico
- utile per debugging retrieval

---

## 4. Domanda naturale con KB attiva

### Prerequisito
/kb use default

### Input
Quali sono i rischi operativi principali di Glass Orchard?

### Flusso
1. Inbound text normale
2. Router valuta se la domanda assomiglia a una domanda KB
3. Se la KB è attiva e il candidato `kb_query` supera la soglia, route = `kb_query`
4. Retrieval top-k
5. Context grounded costruito con i passaggi recuperati
6. Provider `qa` genera risposta grounded
7. Outbound text finale

### Atteso
- se score KB è alto: risposta grounded
- se score KB è basso: fallback a `chat`
- audit utile: `route_source=kb_probe` oppure fallback

---

## 5. News digest

### Input
/news latest ai integration patterns

### Flusso
1. Comando slash passa al runtime
2. Router / explicit command seleziona `news_digest`
3. Tool raccoglie fonti
4. Sintesi dei risultati
5. Outbound text

### Atteso
- digest con più fonti
- struttura leggibile
- niente routing casuale

---

## 6. YouTube summary

### Input
/yt https://www.youtube.com/watch?v=...

### Flusso
1. Slash command passa al runtime
2. Workflow `youtube_summarizer`
3. Recupero transcript
4. Sintesi del contenuto
5. Outbound text

### Atteso
- messaggi di stato chiari
- errore esplicito se transcript mancante o tool fallisce

---

## 7. Python tool

### Input
/py print(2 + 2)

### Flusso
1. Slash command passa al runtime
2. Router esplicito o tool boundary
3. Tool `python`
4. Output serializzato
5. Outbound text

### Atteso
- risultato tool visibile
- boundary chiaro fra chat e tool execution

---

## 8. TTS

### Input
/tts Questo è un test di sintesi vocale.

### Flusso
1. Slash command passa al runtime
2. Tool `tts`
3. Generazione audio file-based
4. Runtime salva `last_audio_path` in session state
5. CLI riceve text + audio info
6. L’utente può poi usare `/play`

### Atteso
- file audio generato
- ultimo audio memorizzato nello state

---

## 9. Podcast

### Input
/podcast differenza tra event-driven systems e job-based automation

### Flusso
1. Slash command passa al runtime
2. Workflow `podcast`
3. Scrittura script
4. Sintesi audio
5. Salvataggio `last_audio_path`
6. Outbound text + outbound audio
7. Possibile replay locale con `/play`

### Atteso
- script e file audio disponibili
- ultimo audio richiamabile

---

## 10. STT

### Input
/stt ./samples/voice_note.ogg

### Flusso
1. Slash command passa al runtime
2. Tool `stt`
3. Staging file audio
4. Trascrizione
5. Outbound text

### Atteso
- percorso audio valido richiesto
- output testuale della trascrizione

---

## 11. File fetch / web

### Input
/fetch https://example.com
/fetch searxng architecture local search

### Flusso
1. Slash command passa al runtime
2. Tool `web`
3. Se URL: fetch
4. Se testo: search
5. Output testuale

### Atteso
- comportamento coerente in CLI e Telegram
- niente black box lato command layer

---

## 12. /route debug

### Input
/route qual è l’architettura del sistema?

### Flusso
1. Comando locale
2. Nessuna esecuzione del turno
3. Serializzazione della decisione del router
4. Output JSON compatto

### Atteso
- utile per capire route, reason, candidate scores

---

## 13. /play locale

### Input
/play
oppure
/play ./workspace/audio/last.wav

### Flusso
1. Comando locale CLI
2. Recupera `last_audio_path` dalla sessione oppure usa il path passato
3. Avvia un player locale se disponibile
4. Nessun passaggio sul bus

### Atteso
- replay rapido di TTS o podcast appena generato
- su Telegram non serve: l’audio viene già inviato come outbound audio

---

## 14. Telegram text / voice / document

### Text
- i messaggi slash e non-slash passano come testo al runtime

### Voice
1. Telegram scarica il vocale
2. Runtime gestisce `inbound.voice_note`
3. STT
4. eventuale follow-up come testo

### Document
1. Telegram scarica il documento
2. Runtime gestisce `inbound.document`
3. se PDF, possibile flusso di ingest

### Atteso
- surface quasi paritetica con la CLI
- differenza principale: `/play` resta locale alla CLI

---

## 15. Flusso di test KB consigliato

1. Generare o verificare `tests/fixtures/data/kb/glass_orchard_story.pdf`
2. `/kb ingest tests/fixtures/data/kb/glass_orchard_story.pdf`
3. `/kb query Dove si trova Serra Vetro?`
4. `/kb query Cos'è Delta-Red?`
5. `/kb use default`
6. porre domande naturali grounded:
   - Quali sono i rischi operativi principali di Glass Orchard?
   - Confronta Prisma-4 e Lantern
   - Perché il dossier dice che il problema era di coordinamento?

Se queste domande funzionano bene, il flusso KB è molto più vicino a essere affidabile.
