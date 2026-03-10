# PICOBOT CLI – GUIDA RAPIDA OPERATIVA

Questa guida mostra come attivare manualmente tutte le funzionalità principali di Picobot dalla CLI.

## Avvio

Avvia il sistema:

```
make start
```

Oppure senza debug:

```
make start-nodebug
```

Il prompt apparirà così:

```
❯
```

## Comandi di sistema

Mostra tutti i comandi disponibili:

```
/help
```

Mostra stato runtime (config, modello, sandbox, KB):

```
/status
```

Lista tool registrati:

```
/tools
```

Uscire dalla CLI:

```
/exit
```

## Chat normale (LLM)

Qualsiasi testo che non è un comando viene gestito come chat.

Esempi:

```
ciao
spiegami cos'è un sistema event-driven
come funziona docker
```

## Python sandbox

Esecuzione codice Python dentro la sandbox Docker.

Forma esplicita:

```
/python print("hello")
```

Esempio:

```
/python for i in range(5): print(i)
```

Oppure tramite routing:

```
python: print(1); print(2); print(3)
```

## News digest

Riassunto notizie tramite web search.

```
/news intelligenza artificiale
/news tecnologia
/news geopolitica
```

Trigger naturale:

```
dammi le ultime notizie sull'intelligenza artificiale
```

## YouTube summarizer

Riassume un video YouTube.

Comando diretto:

```
/yt https://www.youtube.com/watch?v=XXXXXXXX
```

Oppure linguaggio naturale:

```
riassumi questo video https://www.youtube.com/watch?v=XXXXXXXX
```

## Podcast generation

Genera un mini podcast audio.

Trigger naturale:

```
fammi un podcast sull'energia nucleare
voglio un podcast sulla storia di Linux
```

Durata breve predefinita (configurabile).

## Text-to-Speech (TTS)

Converte testo in audio.

Comando diretto:

```
/tts ciao mondo
```

Oppure:

```
converti questo testo in audio: ciao mondo
```

## Speech-to-Text (STT)

Trascrive file audio.

Esempio:

```
/stt file.wav
```

Oppure tramite Telegram voice message.

## Knowledge Base (KB)

Mostra KB attiva:

```
/kb
```

Lista KB disponibili:

```
/kb list
```

Seleziona KB:

```
/kb use nome_kb
```

Ingest documento:

```
/kb ingest documento.pdf
```

Query sulla KB:

```
/kb query di cosa parla il documento?
```

## Memoria sessione

Mostra stato memoria:

```
/mem
```

Ultima history:

```
/mem tail
```

Summary della conversazione:

```
/mem summary
```

Facts estratti:

```
/mem facts
```

## Web fetch

Recupera contenuto pagina:

```
recupera il contenuto di https://example.com
```

Oppure tramite tool diretto:

```
/fetch https://example.com
```

## File sandbox

Operazioni su file nella workspace:

```
/file list
/file read nomefile.txt
/file write nomefile.txt "contenuto"
```

## Debug routing

Per vedere come il router decide:

```
/route spiegami cos'è docker
```

Mostra quale tool/workflow verrebbe usato.

## Sandbox Docker

Aprire shell nel container:

```
make sandbox-shell
```

Verificare stato:

```
make sandbox-status
```

Fermare sandbox:

```
make stop
```

## Workspace

Tutti i file runtime sono sotto:

```
.picobot/workspace
```

Struttura tipica:

```
.picobot/
    workspace/
    tools/
    qdrant/
    config.json
```

## Note utili

• I comandi che iniziano con "/" sono gestiti localmente dalla CLI.

• Tutto il resto passa dal router AI.

• Se un tool non viene triggerato, prova la forma esplicita con "/".

## Test rapido completo

Sequenza consigliata per verificare tutto:

```
ciao
/status
/tools
/news intelligenza artificiale
/python print("hello")
/tts ciao mondo
/yt https://www.youtube.com/watch?v=FDKahWbJV84
fammi un podcast sull'energia nucleare
/kb
/mem
```

Se tutto funziona, il sistema è operativo.

