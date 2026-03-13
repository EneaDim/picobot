# 🏗 Picobot Architecture

This document describes how Picobot works internally.

Picobot is built around a **message-driven runtime orchestrator**.

The system is designed to be:

-   modular
-   observable
-   extensible
-   tool‑centric

------------------------------------------------------------------------

# 🧭 System Overview

High‑level pipeline:

User → CLI → Message Bus → Runtime → Router → Tool/Workflow → Output

Each stage emits events to the runtime bus.

------------------------------------------------------------------------

# 🧠 Runtime Orchestrator

The runtime coordinates every interaction.

Lifecycle of a turn:

1.  receive inbound message
2.  build context
3.  run routing decision
4.  execute tool or workflow
5.  update memory
6.  produce output

------------------------------------------------------------------------

# 📨 Message Bus

The message bus connects all components.

Event types:

inbound.\*\
runtime.\*\
outbound.\*

Example flow:

    inbound.text
    runtime.turn_started
    runtime.route_selected
    runtime.tool.started
    runtime.tool.completed
    outbound.text

------------------------------------------------------------------------

# 🧭 Router

The router determines how a message should be handled.

Possible routes:

-   chat
-   tool
-   workflow
-   retrieval

Routing sources:

-   explicit commands
-   semantic classification
-   fallback logic

------------------------------------------------------------------------

# 🛠 Tool System

Tools are executable capabilities.

Examples:

-   TTS
-   STT
-   YouTube transcript extraction
-   Python execution
-   Web fetch

Each tool is defined via a **ToolSpec**.

------------------------------------------------------------------------

# 🐳 Docker Sandbox

Tools run inside a persistent container.

Advantages:

-   stable runtime
-   isolated dependencies
-   safe execution

Workspace mapping:

    .picobot/workspace → /workspace

------------------------------------------------------------------------

# 🧠 Memory

Picobot maintains:

-   conversation history
-   extracted facts
-   summaries

Memory is updated after each turn.

------------------------------------------------------------------------

# 🔎 Retrieval

Optional retrieval system combining:

-   vector embeddings
-   BM25 ranking
-   hybrid scoring

Used for knowledge base queries.

------------------------------------------------------------------------

# 🔭 Observability

Picobot emits structured runtime events.

Example trace:

    📥 turn opened
    🧭 routing
    🛠 tool execution
    🧠 memory update
    🏁 turn completed

This helps developers understand system behavior.

------------------------------------------------------------------------

# 🔌 Extensibility

New tools can be added by:

1.  defining a ToolSpec
2.  implementing a handler
3.  registering it

New LLM providers can also be added easily.

------------------------------------------------------------------------

# 🔮 Future Directions

Planned improvements:

-   plugin architecture
-   graphical interface
-   advanced workflows
-   distributed execution
