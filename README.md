# picobot 🤖✨

A local-first agent that combines:

* **Chat + tools** (YouTube transcript/summary, PDF ingest)
* **Retrieval** (local KB with BM25 search)
* **Memory** (global + per-session)
* **Channels**: CLI + Telegram
* **Local LLM via Ollama**

Designed to be hackable, testable, and pleasant to run from a terminal.

---

## Features

### 🧭 Agent orchestration

* Routes each user message to either:

  * **Chat** (LLM answer)
  * **Tool** (e.g., YouTube transcript/summary, PDF ingestion)
  * **KB query** (when asking about already-ingested docs)
* Keeps a **session history** and can maintain a **rolling session summary**.

### 🔎 Local retrieval (KB)

* Ingest PDFs into a local knowledge base.
* Query the KB (BM25-based) to answer doc-specific questions.
* Supports per-chat KB isolation in Telegram (recommended).

### 🧠 Memory

* Global `MEMORY` + session memory.
* “Remember keyword …” workflows (and recall).

### 🛠 Tools

* **YouTube transcript** via `yt-dlp` subtitles:

  * Prefers auto-subs, defaults to **English** to reduce rate limits.
  * Robust to partial failures (e.g., HTTP 429 on one language) if at least one VTT is available.
* **YouTube summary**: transcript → LLM summary
* **PDF ingest tool**: chunk + store into KB

### 💬 Telegram channel

* Text messages → agent
* PDF documents → auto ingest into KB (dedup supported)
* Voice/audio → optional **STT pipeline**:

  * download → ffmpeg convert → whisper.cpp → agent
* Command parity with CLI via shared command dispatcher.

---

## Repository layout

```
picobot/
  agent/        Orchestrator, router, memory
  bus/          Simple event queue
  channels/     CLI/Telegram adapters
  cli/          CLI entrypoints
  config/       Config schema + loader + template
  providers/    LLM providers (Ollama)
  retrieval/    KB ingest + store + BM25
  session/      Session manager
  tools/        Tool specs + registry + init-tools installers
  ui/           Console UI + shared commands
  utils/        Helpers

tests/          Pytest suite
```

---

## Requirements

* Python **3.12+**
* `make`
* **Ollama** (for local LLM)
* Optional binaries (auto-installed by `make init-tools` if configured):

  * `yt-dlp`
  * `ffmpeg`
  * `whisper.cpp` (plus model)
  * `piper` (TTS)

---

## Install

### 1) Create venv + install deps

```bash
python -m venv .venv
source .venv/bin/activate
make dev
```

### 2) Initialize config + tools

```bash
make init
make init-tools
```

This creates a `.picobot/` workspace (ignored by git) and downloads tool bundles/models into `.picobot/tools/`.

---

## Ollama setup (local LLM)

### Install Ollama

* Linux/macOS: install via the official instructions.
* Ensure `ollama` is running:

```bash
ollama --version
ollama serve
```

### Pull models

Pick a chat model and (optionally) an embedding model.

Examples:

```bash
# chat model
ollama pull qwen2.5:3b-instruct-q4_0

# alternative chat model
ollama pull qwen2.5:3b

# embeddings (if you later wire them in)
ollama pull nomic-embed-text
```

Then point your `config.json` to the model name you pulled (see below).

---

## Configuration

Start from the template:

* `picobot/config/config.template.json`

You’ll typically copy it into `.picobot/config.json`:

```bash
cp picobot/config/config.template.json .picobot/config.json
```

### Tool paths (typical)

```json
{
  "tools": {
    "base_dir": ".picobot/tools",
    "whisper_cpp_dir": ".picobot/tools/whisper.cpp",
    "whisper_cpp_main_path": ".picobot/tools/whisper.cpp/build/bin/whisper-cli",
    "whisper_model": ".picobot/tools/whisper.cpp/models/ggml-small.bin",

    "ytdlp_bin": ".picobot/tools/yt-dlp/bin/yt-dlp",
    "ytdlp_args": ["--js-runtimes", "node:/usr/bin/node"],

    "ffmpeg_bin": ".picobot/tools/ffmpeg/bin/ffmpeg",

    "piper_bin": ".picobot/tools/piper/bin/piper",
    "piper_model_it": ".picobot/tools/piper/models/it_IT-paola-medium.onnx",
    "piper_model_en": ".picobot/tools/piper/models/en_US-lessac-medium.onnx"
  }
}
```

Notes:

* `whisper_cpp_main_path` is needed if your build does not place a `main` binary at the project root.
* `ytdlp_args` may be optional depending on your `yt-dlp` version and environment.

---

## Quickstart

### CLI chat

```bash
make chat
```

Try:

* `summarize this youtube video: https://www.youtube.com/watch?v=ssYt09bCgUY&t=6s`
* `ingest pdf /path/to/file.pdf`
* Ask a question about the document you ingested.

### Telegram bot

1. Create a bot via **@BotFather** and copy the token.
2. Put it in `.picobot/config.json` under `telegram.bot_token`.
3. Run:

```bash
make telegram
```

Telegram behaviors:

* Text → agent response
* PDF → auto-ingest (dedup)
* Voice/audio → STT (if enabled)

Useful Telegram commands:

* `/help`
* `/session` (show)
* `/session list`
* `/session set <id>`

---

## How the tool flow works

### High-level pipeline

1. **Router** inspects user input:

   * very short → chat
   * YouTube URL → tool (yt_summary / yt_transcript)
   * PDF ingest request → tool (kb_ingest_pdf)
   * doc question → KB query

2. **Orchestrator** executes the selected path:

   * calls the tool handler
   * or calls the provider (Ollama)
   * optionally fetches retrieval hits
   * merges memory + session summary into context

3. **TurnResult** is emitted:

   * `action`: chat / tool / kb_query
   * `content`: final text
   * `kb_mode`: keep/auto

### YouTube summary path

* `yt_summary` → calls `yt_transcript` → fetches `.vtt` subtitles via `yt-dlp` → cleans VTT → passes transcript to LLM summarizer.

Robustness notes:

* Uses auto-subs first.
* Defaults to English languages to reduce HTTP 429.
* Considers success when at least one `.vtt` is present, even if a subset of requested languages fails.

### PDF ingestion path

* Telegram/CLI triggers `kb_ingest_pdf` tool
* PDF → chunking → store in local KB
* Later questions route to `kb_query` for retrieval + answer synthesis.

---

## Makefile commands

```bash
make dev         # install with dev extras
make test        # run pytest
make lint        # ruff check
make fmt         # ruff format
make init        # create workspace/config
make init-tools  # download/verify external tool bundles
make chat        # run CLI
make telegram    # run Telegram bot
```

---

## Tests (what each one covers)

All tests live under `tests/` and are designed to validate routing, tools, retrieval, memory, and channels.

### `tests/conftest.py`

Shared pytest fixtures and helpers used across the suite.

### `tests/test_router.py`

Validates the router’s decision-making:

* Detects YouTube URLs and routes to tool.
* Routes short messages to chat.
* Routes doc questions to KB query when index is present.

### `tests/test_tools_routing.py`

Ensures end-to-end routing triggers the correct tool name for tool-like prompts.

### `tests/test_tool_validation.py`

Checks tool schema validation:

* correct argument parsing
* invalid inputs rejected with clear errors

### `tests/test_tools_execution.py`

Runs a tool-path turn through the orchestrator while stubbing external dependencies:

* monkeypatch transcript handler to avoid network
* confirms `yt_summary` produces the expected success marker

### `tests/test_ingest_and_search.py`

Exercises retrieval ingestion + search:

* ingest a small sample doc
* verify stored chunks
* verify BM25 returns relevant hits

### `tests/test_retrieval_guardrails.py`

Validates retrieval guardrails:

* behavior when KB is empty
* behavior when retrieval is disabled
* ensures the agent doesn’t hallucinate “indexed docs”

### `tests/test_memory_injection.py`

Checks that memory is correctly injected into prompt context for the LLM.

### `tests/test_memory_recall_general.py`

Validates the “remember / recall” flow and that prior memory is retrievable.

### `tests/test_session.py`

Ensures SessionManager behavior:

* create/get sessions
* persistence/serialization of session state
* session summaries or turn history basics

### `tests/test_debug_router_dump.py`

Checks debug output / dump behavior (routing visibility) when debug flags are enabled.

### `tests/test_e2e_flow.py`

A higher-level smoke test:

* exercises a realistic multi-turn flow
* checks that a turn returns a structured result

### `tests/test_telegram_mock.py`

Unit test for Telegram channel behavior using mocks:

* ensures message handlers call orchestrator
* checks session mapping from chat_id

### `tests/test_telegram_automations.py`

Validates Telegram automations:

* PDF auto-ingest triggers KB ingest tool
* dedup map prevents repeated ingest
* voice/audio STT routing when enabled

---

## Troubleshooting

### YouTube: HTTP 429 Too Many Requests

* Reduce requested languages (default EN is safest)
* Retry later
* Consider using cookies or a proxy (advanced)

### YouTube: JavaScript runtime warnings

Some `yt-dlp` versions warn about missing JS runtime. If extraction fails, configure:

```json
"ytdlp_args": ["--js-runtimes", "node:/usr/bin/node"]
```

### whisper.cpp: main not found

Set:

```json
"whisper_cpp_main_path": ".picobot/tools/whisper.cpp/build/bin/whisper-cli"
```

### Piper: missing shared libraries

Ensure the wrapper uses bundled libs. `make init-tools` should generate a working wrapper in:

* `.picobot/tools/piper/bin/piper`

---

## Roadmap ideas

* Telegram: richer command set (memory/kb inspection)
* Audio fallback when subtitles are unavailable (yt-dlp → bestaudio → whisper)
* Better caching for YouTube transcripts
* More tool adapters (calendar/email/etc.)


