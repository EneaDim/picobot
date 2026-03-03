# picobot 🤖✨

**picobot** is a **local-first** agent that runs entirely on your machine:

* 🧠 **Local LLM** via **Ollama**
* 🧭 **Router + Orchestrator** (deterministic routing, minimal prompts)
* 🛠️ **Tooling** (YouTube transcript/summary, retrieval KB, sandboxed file/web/python, podcast generator)
* 🔎 **Retrieval** (local KB, BM25)
* 📝 **Memory** (global + per-session)
* 🎙️ **Audio**: STT (**whisper.cpp**) + TTS (**piper** / optional qwen_tts)
* 💬 **Channels**: CLI + Telegram (shared command surface)

The design goal: **lightweight, deterministic, hackable**, and friendly to run from a terminal.

---

## Why picobot

Most “agents” assume cloud APIs, complex orchestration frameworks, and non-deterministic behavior.

picobot is intentionally different:

* ✅ **Local-only**: no cloud APIs required
* ✅ **Deterministic** routing (router produces a single JSON line)
* ✅ **Tools are sandboxed** (subprocess runner with allowlist + timeouts)
* ✅ **Errors never leak to Telegram** (details only on terminal)
* ✅ **Minimal prompts** and predictable turn flow

---

## High-level architecture

### Core loop

Each message goes through a tight pipeline:

1. **Language resolution** (rule-based, no LLM)
2. **Router** decides: `chat` or `tool` (or `kb_query` mapped to tool)
3. **Orchestrator** executes one full turn:

   * memory updates / recall
   * tool execution (if any)
   * retrieval (if enabled)
   * final response (target: short, 6–8 sentences)
4. **UI** renders output

### Key modules

* `picobot/agent/router.py` → deterministic routing → **one-line JSON**
* `picobot/agent/orchestrator.py` → executes a full turn
* `picobot/agent/memory.py` → memory store + injection helpers
* `picobot/tools/*` → tools with a **standard result contract**
* `picobot/tools/terminal_tool.py` + `sandbox_exec.py` → sandboxed subprocess execution
* `picobot/retrieval/*` → local KB ingest + BM25 search
* `picobot/channels/*` → CLI + Telegram adapters
* `picobot/ui.py` → unified UI surface + shared commands/autocomplete

---

## Tool contract

Every tool returns the same shape:

```json
{
  "ok": true,
  "data": {"...": "..."},
  "error": null,
  "language": "it"
}
```

Rules:

* Tools **never** print to Telegram
* Tools do not embed complex agent logic
* Tool errors are logged in terminal; user-facing channel response stays short and safe

---

## Sandboxed terminal execution

Any tool that runs external binaries must go through the sandboxed runner:

* `picobot/tools/sandbox_exec.py` → allowlist + timeout + output caps
* `picobot/tools/terminal_tool.py` → shared base helpers + terminal-only logging

This is used by (and intended for):

* `yt-dlp` (YouTube transcript/summary)
* `ffmpeg`
* `whisper.cpp`
* `piper`
* future “terminal tools”

---

## Repository layout

```txt
picobot/
  agent/        router + orchestrator + prompts + memory
  bus/          lightweight event queue (if/when needed)
  channels/     CLI + Telegram adapters
  cli/          CLI entrypoints
  config/       schema + loader + template
  providers/    local LLM providers (Ollama)
  retrieval/    KB ingest + BM25 store/query
  session/      session manager + state
  tools/        tool specs + sandbox tools + youtube + podcast
  ui.py         unified UI + shared commands/autocomplete
  utils/        helpers

tests/          pytest suite
```

---

## Requirements

* Python **3.12+**
* `make`
* **Ollama** (local LLM)
* Optional local binaries (often installed via `make init-tools` depending on your setup):

  * `yt-dlp`
  * `ffmpeg`
  * `whisper.cpp` + model
  * `piper` + voice models

---

## Install

### 1) Create venv + install deps

```bash
python -m venv .venv
source .venv/bin/activate
make dev
```

### 2) Initialize workspace + config

```bash
make init
cp picobot/config/config.template.json .picobot/config.json
```

### 3) (Optional) Install tool bundles

```bash
make init-tools
```

---

## Ollama setup

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b-instruct-q4_0
```

Then ensure your `.picobot/config.json` points to the same model name.

---

## Configuration

Start from:

* `picobot/config/config.template.json`

Notes:

* The schema is **legacy-friendly**: both old flat keys and new structured keys are accepted.
* Tool binaries and models can be configured via `tools.*`.

Key sections you’ll likely touch:

* `ollama` → local LLM model + timeout
* `retrieval` → enable/disable KB and retrieval parameters
* `tools` → local tool binary paths and YouTube args
* `podcast` → voices, triggers, output format
* `telegram` → bot token + channel behavior

---

## Quickstart

### CLI

```bash
make chat
```

Try:

* `ping`
* `remember paprika`
* `what did i ask you to remember?`
* Paste a YouTube URL
* `/kb set demo` → `/kb ingest` → ask a question about your docs
* `/py print(2+2)`
* `/file preview ./docs/demo/source/test.txt`
* `/podcast it calabria e tradizioni`

### Telegram

1. Create a bot with **@BotFather**
2. Put token into `.picobot/config.json` → `telegram.bot_token`
3. Run:

```bash
make telegram
```

Telegram behavior:

* Text → agent
* PDF → optional auto-ingest into KB
* Voice/audio → optional STT pipeline

---

## How routing works

The router is intentionally small:

* decides **only**: `chat` or `tool` (+ tool name + args)
* emits **single-line JSON**
* no tool calls, no complex parsing, no business logic

The orchestrator:

* resolves language
* applies deterministic shortcuts (`ping`, `remember`)
* calls router
* executes tools/retrieval when needed
* calls LLM for final response

**KB auto-routing is opt-in** (recommended): you can enable it explicitly via session/UI commands so normal questions don’t accidentally hit retrieval.

---

## YouTube tool

Pipeline:

1. `yt_transcript` uses `yt-dlp` to download subtitles (auto subs included)
2. transcripts are cleaned (VTT/SRT → plain text)
3. `yt_summary` summarizes transcript via local LLM

Sandboxed:

* `yt-dlp` is executed via `TerminalToolBase` (allowlist + timeout + output caps)

Common issues:

* **HTTP 429**: YouTube rate limit → retry later / reduce languages / use cookies (advanced)
* **JS runtime warnings**: configure `--js-runtimes` (node/deno)

---

## Podcast generator

Config-driven triggers (IT/EN) generate a short podcast:

* Pure dialogue format:

  * `NARRATOR:`
  * `EXPERT:`
* Two voices required
* Duration defaults to 1 minute, hard cap 2 minutes
* Output: mp3/ogg (config)

---

## KB (retrieval)

* Ingest documents into a named KB
* Query using BM25
* Orchestrator uses retrieval context to answer

Useful CLI commands:

* `/kb set <name>`
* `/kb status`
* `/kb ingest`
* `/kb on` / `/kb off` (behavior depends on your UI implementation)

---

## Development

### Lint / tests

```bash
ruff check .
pytest -q
```

### Makefile

```bash
make dev         # install dev deps
make test        # pytest
make lint        # ruff
make fmt         # ruff format
make init        # create workspace/config
make init-tools  # download/verify external tool bundles
make chat        # CLI
make telegram    # Telegram bot
```

---

## Next steps (roadmap)

### 1) Finalize the agent structure

* Make the router contract fully explicit in tests (tool args schemas + deterministic output)
* Tighten orchestrator response policy (max sentences, consistent formatting)
* Add explicit “tool rendering” layer (per tool name)

### 2) Expand terminal-based tools

* Whisper pipeline tool (audio → wav → whisper.cpp → text)
* ffmpeg helper tool (safe audio/video transforms)
* YouTube fallback: bestaudio → whisper (when subtitles missing)

### 3) Automatic sub-agents (local)

Introduce a **sub-agent generation** workflow (still local-first):

* A small “agent spec” format (JSON/YAML)
* Codegen for:

  * prompt pack entries
  * router tool signatures
  * tool scaffolding
  * tests

Goal: adding a new tool should feel like:

* define schema + contract
* implement handler
* register tool
* get e2e tests for free

### 4) Better caching + reproducibility

* Cache YouTube transcripts by video ID
* Cache retrieval index builds
* Add deterministic fixtures for tool outputs

---

## License

(TODO)

