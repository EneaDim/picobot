# 🤖 Picobot

**Picobot** is a modular AI assistant that orchestrates **LLMs, tools,
and workflows** from a unified CLI environment.

It combines:

-   🧠 Large Language Models
-   🛠 Tool execution
-   🧭 Intelligent routing
-   🐳 Sandbox runtime
-   🎙 Audio pipelines
-   📚 Knowledge retrieval

Picobot is designed to be **extensible, observable, and
developer‑friendly**.

------------------------------------------------------------------------

# ✨ Key Capabilities

## 🧭 Intelligent Routing

Picobot analyzes each message and decides how to process it.

Possible actions:

-   💬 Chat with an LLM
-   🛠 Execute a tool
-   📚 Query a knowledge base
-   🔄 Run a workflow

Example runtime trace:

    📥 turn opened
    🧭 routing decision
    🧠 thinking
    🛠 tool execution
    ✅ result

------------------------------------------------------------------------

## 🛠 Built‑in Tools

Picobot includes a growing ecosystem of tools.

Examples:

-   🎙 **TTS** --- text‑to‑speech (Piper)
-   🎧 **STT** --- speech‑to‑text (whisper.cpp)
-   📺 **YouTube processing**
-   🐍 **Python sandbox execution**
-   🌐 **Web fetching**
-   🎙 **Podcast generation**

Tools run inside a **Docker sandbox** for reliability.

------------------------------------------------------------------------

## 🐳 Sandbox Runtime

Tools run inside a dedicated container.

Benefits:

-   reproducible environment
-   dependency isolation
-   consistent audio/video tooling

Included utilities:

-   ffmpeg
-   yt-dlp
-   whisper.cpp
-   piper

------------------------------------------------------------------------

# 🧠 LLM Providers

Picobot currently supports:

### 🦙 Ollama

Local or remote inference server.

### ✨ Gemini

Google's Gemini API.

Providers are interchangeable thanks to a unified abstraction layer.

------------------------------------------------------------------------

# 🚀 Quickstart

## 1️⃣ Clone repository

    git clone <repo>
    cd picobot

## 2️⃣ Create environment

    make venv
    source .venv/bin/activate

## 3️⃣ Install project

    make install

## 4️⃣ Initialize runtime

    make init

This step will:

-   generate configuration
-   build the Docker sandbox
-   install runtime tools
-   verify environment health

------------------------------------------------------------------------

## 5️⃣ Start Picobot

    make start

or

    make start-nodebug

------------------------------------------------------------------------

# 🧑‍💻 CLI Usage

## Help

    /help

## Text to Speech

    /tts Hello world

## Speech to Text

    /stt audio.wav

## YouTube Transcript

    /yt https://youtube.com/...

## Python Execution

    /python print(2+2)

## Web Fetch

    /fetch https://example.com

## Podcast

    /podcast explain quantum computing

------------------------------------------------------------------------

# ⚙ Configuration

All settings are stored in:

    .picobot/config.json

Main sections:

-   LLM providers
-   sandbox runtime
-   tools
-   embeddings
-   retrieval

------------------------------------------------------------------------

# 🧪 Development

Run tests:

    make test

Inspect tools:

    make tools-doctor

Open sandbox shell:

    make sandbox-shell

------------------------------------------------------------------------

# 📚 Documentation

Additional documentation:

-   ARCHITECTURE.md
-   TUTORIAL.md

------------------------------------------------------------------------

# 🪪 License

MIT License
