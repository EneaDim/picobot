# Picobot Architecture

## Overview

Picobot è un assistente AI local-first, event-driven, multi-channel.

Il sistema è organizzato attorno a questo flusso:

**Channels → Bus → Runtime → Agent Core → Tools / Routing / Retrieval → Runtime → Bus → Channels**

Obiettivi architetturali attuali:

- local-first
- runtime event-driven
- canali disaccoppiati dal core agente
- tools modulari
- routing e retrieval separati
- osservabilità tramite runtime events
- struttura semplice, leggibile e mantenibile

---

## Core architectural primitives

### MessageBus
Bus async in-memory che collega canali, runtime e servizi interni.

### InboundMessage
Messaggi in ingresso nel sistema.

Esempi:
- testo da CLI
- testo da Telegram
- voice note Telegram
- documento Telegram
- cron tick
- heartbeat tick

### OutboundMessage
Messaggi prodotti dal sistema verso i canali.

Esempi:
- risposta testuale
- audio generato
- status update
- errore runtime/tool

### RuntimeEvent
Eventi interni per tracing, debug e osservabilità.

Esempi:
- turn started
- route selected
- context built
- tool started/completed/failed
- retrieval started/completed
- memory updated
- cron started/completed/failed
- heartbeat snapshot
- turn completed/failed

---

## End-to-end flow

## 1. CLI text flow

1. `picobot.app.main` bootstrap:
   - carica config
   - crea bus
   - crea provider
   - crea runtime
   - crea channel manager
   - registra `CLIChannel`

2. utente scrive un messaggio nella CLI

3. `CLIChannel.send_text()` pubblica:
   - `inbound.text`

4. `AgentRuntime` riceve il messaggio:
   - apre/risolve la sessione
   - emette `runtime.turn_started`
   - crea runtime hooks
   - invoca `Application.one_turn(...)`

5. `TurnProcessor`:
   - seleziona la route
   - dispatcha workflow o tool
   - aggiorna memoria/stato
   - produce `TurnResult`

6. `AgentRuntime`:
   - emette `runtime.turn_completed`
   - pubblica `outbound.text` / `outbound.audio` / `outbound.error`

7. `ChannelManager` consegna l’outbound a `CLIChannel`

8. `CLIChannel` rende disponibili i messaggi al loop CLI

---

## 2. Telegram text flow

1. `TelegramChannel` riceve un messaggio testuale
2. pubblica `inbound.text`
3. `AgentRuntime` esegue lo stesso flow della CLI
4. `ChannelManager` inoltra `outbound.*` a `TelegramChannel`
5. `TelegramChannel` invia messaggio/audio su Telegram

---

## 3. Telegram voice note flow

1. `TelegramChannel` scarica il file audio
2. pubblica `inbound.telegram.voice_note`
3. `TelegramInboundHandler`:
   - esegue STT tramite tool `stt`
   - ottiene la trascrizione
   - ripubblica `inbound.text`
4. `AgentRuntime` processa il testo trascritto come un normale turn
5. output restituito a Telegram

---

## 4. Telegram document flow

1. `TelegramChannel` scarica il file
2. pubblica `inbound.telegram.document`
3. `TelegramInboundHandler`:
   - verifica il tipo file
   - se PDF, prova ingest KB via `kb_ingest_pdf`
   - emette runtime events e outbound status/error
4. se ingest riuscito, l’utente riceve conferma

---

## 5. Heartbeat flow

1. `heartbeat.service` pubblica `inbound.heartbeat_tick`
2. `HeartbeatHandler` riceve il tick
3. pubblica `runtime.heartbeat.snapshot`

---

## 6. Cron flow

1. `cron.service` pubblica `inbound.cron_tick`
2. `CronHandler` identifica il `job_name`
3. emette:
   - `runtime.cron.job_started`
   - `runtime.cron.job_completed`
   - `runtime.cron.job_failed`

---

## Agent core

Il core agente è nel package `picobot.agent`.

### `application.py`
Composition root del core agente.

Responsabilità:
- costruisce i servizi del core
- registra i tool
- espone la facade del turn
- collega route selection, workflow dispatch, tool execution e memory/context

### `turn_processor.py`
Owner del turn pipeline.

Responsabilità:
- route selection
- dispatch del workflow/tool corretto
- emissione hook turn-level
- update della memoria
- update stato audio
- composizione finale del `TurnResult`

### `workflow_dispatcher.py`
Contiene la logica dei workflow applicativi.

Workflow attuali:
- chat
- kb_query
- news_digest
- youtube_summarizer
- podcast
- explicit_tool

### `tool_executor.py`
Boundary per l’esecuzione tool.

Responsabilità:
- resolve tool name
- validazione input
- esecuzione handler
- emissione hook:
  - tool started
  - tool completed
  - tool failed

### `memory_context_service.py`
Boundary per memoria e contesto.

Responsabilità:
- append della history
- update del session state
- context assembly per il modello

### `route_selection.py`
Boundary del routing usato dal core agente.

Responsabilità:
- eseguire route selection
- restituire un risultato strutturato
- nascondere al turn processor il dettaglio del router sottostante

### `models.py`
Tipi del core agente.

Contiene:
- `RuntimeHooks`
- `TurnResult`

---

## Runtime

Il runtime è nel package `picobot.runtime`.

### `agent_runtime.py`
Coordinatore runtime principale.

Responsabilità:
- subscribe agli inbound
- delega a handler dedicati per cron/heartbeat/telegram speciali
- invoca il turn agente per `inbound.text`
- pubblica output ed eventi tramite `RuntimeEventPublisher`

### `event_publisher.py`
Publisher centralizzato del runtime.

Responsabilità:
- costruire envelope uniformi per runtime events
- pubblicare outbound messages
- costruire i `RuntimeHooks` per turno

### `heartbeat_handler.py`
Handler dedicato per heartbeat.

Responsabilità:
- ricevere `inbound.heartbeat_tick`
- produrre `runtime.heartbeat.snapshot`

### `cron_handler.py`
Handler dedicato per cron.

Responsabilità:
- ricevere `inbound.cron_tick`
- dispatchare job cron registrati
- produrre eventi start/completed/failed

### `telegram_inbound_handler.py`
Handler runtime per inbound Telegram non testuali.

Responsabilità:
- voice note → STT → `inbound.text`
- document PDF → ingest KB best-effort

---

## Channels

I canali sono nel package `picobot.channels`.

### `base.py`
Contratto base dei channel adapter.

### `manager.py`
Dispatcher outbound centralizzato.

Responsabilità:
- sottoscriversi a `outbound.*`
- inoltrare ogni messaggio al channel corretto

### `cli.py`
Channel adapter della CLI.

Responsabilità:
- pubblicare `inbound.text`
- raccogliere `outbound.*`
- esporre queue locale al loop CLI

### `telegram.py`
Channel adapter Telegram.

Responsabilità:
- text → `inbound.text`
- voice note → `inbound.telegram.voice_note`
- document → `inbound.telegram.document`
- ricevere `outbound.text/status/error/audio`
- consegnare i messaggi su Telegram

---

## Bus

### `bus/events.py`
Definisce:
- `InboundMessage`
- `OutboundMessage`
- `RuntimeEvent`

Più factory helper per creare messaggi ed eventi.

### `bus/queue.py`
Implementa `MessageBus`.

Responsabilità:
- publish/subscribe async
- dispatch per tipo messaggio
- backbone intra-process del sistema

---

## Context and memory

### `context/context_builder.py`
Costruisce `ContextAssembly` e `ModelContext`.

Input:
- session state
- history
- summary
- memory facts
- retrieval context
- runtime context

### `context/model_context.py`
Rappresentazione del contesto finale verso il modello.

Responsabilità:
- supporting context
- rendering messaggi modello
- `to_messages()`

### `memory/stores.py`
Store persistenti per:
- session state
- history
- summary
- facts

### `memory/manager.py`
Manager operativo usato dal core per append/history memory.

### `session/manager.py`
Gestione sessioni e path session-specifici.

---

## Routing subsystem

Il routing è nel package `picobot.routing`.

### `deterministic.py`
Entry point del routing usato dal core agente.

### `documents.py`
Parsing dei route docs markdown.

### `embedder.py`
Embedding del routing.

### `qdrant_router_store.py`
Vector store del routing, opzionale.

### `reranker.py`
Reranking dei candidati.

### `router_index.py`
Gestione/creazione dell’indice routing.

### `router_policy.py`
Policy decisionali del routing.

### `router_retriever.py`
Retriever dei candidati route.

### `router_service.py`
Servizio principale del routing.

### `schemas.py`
Tipi e schemi del routing.

### `knowledge/routing_kb/routes/*.md`
Knowledge assets che descrivono tool e workflow candidati al routing.

---

## Retrieval subsystem

Il retrieval è nel package `picobot.retrieval`.

### `bm25.py`
Indice lessicale BM25.

### `embedder.py`
Embedding locale per documenti.

### `ingest.py`
Pipeline di ingest documentale in KB.

### `qdrant_docs_store.py`
Vector store documentale Qdrant, opzionale.

### `query.py`
Query retrieval ibrida.

### `schemas.py`
Tipi e schemi del retrieval.

### `store.py`
Layout/storage locale della KB.

---

## Tools subsystem

Il sistema tools è nel package `picobot.tools`.

### `base.py`
Contratto base dei tool.

### `registry.py`
Registry dei tool disponibili.

### `terminal_tool.py`
Base per tool eseguiti via terminale.

### `sandbox_exec.py`
Utility per esecuzione tool in sandbox.

### `paths.py`
Risoluzione dei path tool/binari locali.

### `init_tools.py`
Bootstrap/installazione di binari e modelli locali.

### Tool specifici
- `file.py` → file system tool
- `python.py` → python sandbox tool
- `web.py` → fetch web singolo
- `web_search.py` → ricerca web locale
- `news_digest.py` → raccolta items per digest news
- `retrieval.py` → tool KB query / ingest
- `youtube.py` → transcript e summary YouTube
- `podcast.py` → generazione podcast/audio
- `stt.py` → speech-to-text locale
- `tts.py` → text-to-speech locale

---

## Providers

### `providers/ollama.py`
Provider LLM locale via Ollama.

### `providers/types.py`
Tipi condivisi dei provider.

---

## Services

### `services/search_backend.py`
Protocol del backend search.

### `services/searxng_backend.py`
Backend locale SearXNG.

### `services/web_search_service.py`
Facade search/news sopra backend locali.

---

## Sandbox

### `sandbox/runner.py`
Runner locale subprocess.

### `sandbox/docker_runner.py`
Runner persistente Docker.

---

## App / bootstrap

### `app/main.py`
Bootstrap applicativo completo:
- load config
- create bus
- create runtime
- create channel manager
- register CLI
- register Telegram opzionale
- run interactive CLI loop

### `app/bootstrap.py`
Export minimale dei punti di avvio.

### `__main__.py`
Entry point package.

---

## Config

### `config/schema.py`
Schema typed della config.

### `config/loader.py`
Load/normalizzazione config.

### `config/init.py`
Init config/progetto.

### `config/config.template.json`
Template config principale.

### `config/setting.template.searxng.yml`
Template config SearXNG.

### `runtime_config.py`
Accesso config runtime condiviso.

---

## Prompts

### `prompts/base.py`
Prompt di base del sistema.

### `prompts/kb.py`
Prompt per risposte grounded su KB.

### `prompts/language.py`
Utility/rilevazione lingua.

### `prompts/podcast.py`
Prompt per podcast/script.

### `prompts/tools.py`
Prompt/utility collegati ai tool.

---

## UI

### `ui/commands.py`
Comandi applicativi e utility UX:
- KB
- sessioni
- podcast
- comandi supporto CLI

---

## Utilities and support

### `utils/helpers.py`
Helper generici.

### `dev/scripts/make_test_pdf.py`
Generatore PDF di test.

### `docker/picobot-sandbox.Dockerfile`
Dockerfile della sandbox.

### `infra/searxng/docker-compose.yml`
Compose del backend search locale.

### `infra/searxng/config/settings.yml`
Config SearXNG.

---

## Tests

### `tests/conftest.py`
Fixture condivise.

### `tests/test_config.py`
Test config.

### `tests/test_init_tools.py`
Test bootstrap tools.

### `tests/test_news_summarizer_render.py`
Test render news digest.

### `tests/test_orchestrator_chat.py`
Test del flow chat agente.

### `tests/test_podcast_trigger.py`
Test trigger podcast.

### `tests/test_prompts.py`
Test prompt helpers.

### `tests/test_registry.py`
Test tool registry.

### `tests/test_router_docs.py`
Test validità route docs.

### `tests/test_router_smoke.py`
Smoke test routing.

### `tests/test_tool_validation.py`
Test validazione tools.

### `tests/test_ui_commands.py`
Test UI commands.

---

## Current strengths

- runtime event-driven reale
- core agente separato in servizi leggibili
- CLI e Telegram allineati al bus
- routing e retrieval distinti
- tools local-first con sandbox e host-local dove serve
- buona osservabilità runtime
- struttura repository finalmente ordinata

---

## Current remaining gaps

I gap rimasti sono di rifinitura, non di struttura:

1. summary lifecycle ancora minimale
2. context truncation policy ancora essenziale
3. heartbeat ancora poco ricco
4. cron jobs reali ancora pochi
5. inbound Telegram speciali da hardenare meglio su payload/schema/policy
6. alcuni workflow possono ancora essere ulteriormente separati se crescono
