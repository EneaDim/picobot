from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class MemoryLimits(BaseModel):
    max_history_lines: int = 400
    tail_lines: int = 120


class SummaryConfig(BaseModel):
    mode: str = "single"
    max_chars: int = 24000
    chunk_chars: int = 7000
    max_chunks: int = 6
    timeout_s: int = 600
    output_language: str = "auto"


class KBConfig(BaseModel):
    auto_candidates: list[str] = Field(default_factory=list)


class OllamaConfig(BaseModel):
    timeout_s: float = 120.0
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b-instruct-q4_0"


class UIConfig(BaseModel):
    use_emojis: bool = True
    use_prompt_toolkit: bool = True
    vi_mode: bool = False


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    voice_stt_enabled: bool = True
    echo_transcript: bool = False


class ToolsConfig(BaseModel):
    # keep legacy naming and add what we need for Telegram STT later
    base_dir: str = ""
    whisper_cpp_dir: str = ""
    whisper_model: str = ""
    ytdlp_bin: str = ""
    ytdlp_args: list[str] = Field(default_factory=list)
    ffmpeg_bin: str = "ffmpeg"
    arecord_bin: str = "arecord"
    aplay_bin: str = "aplay"
    piper_bin: str = ""
    piper_model_it: str = ""
    piper_model_en: str = ""

    # optional explicit paths used by adapters/tools
    whisper_cpp_main_path: str = "./whisper.cpp/main"


class RetrievalConfig(BaseModel):
    enabled: bool = True

    bm25_candidates: int = 12
    top_k: int = 3
    max_embed_chars: int = 4000
    max_context_chars: int = 5000

    # ingest settings (kept minimal)
    chunk_chars: int = 900
    chunk_overlap: int = 120
    bm25_k1: float = 1.5
    bm25_b: float = 0.75


class WebConfig(BaseModel):
    enabled: bool = False
    allowlist: list[str] = Field(default_factory=list)
    timeout_s: float = 8.0


class DebugConfig(BaseModel):
    enabled: bool = False


class Config(BaseModel):
    """
    Block-based config (required), but legacy-friendly.
    The loader will normalize legacy flat keys into these blocks.
    """
    model_config = ConfigDict(extra="ignore")

    workspace: str = str(Path.home() / ".picobot" / "workspace")

    # legacy-friendly “top-level” concepts
    default_kb_name: str = "default"
    default_language: str = "it"

    embedding_model: str = "nomic-embed-text:latest"
    summarizer_model: str = "qwen2.5:3b-instruct-q4_0"
    use_embeddings: bool = False

    memory_limits: MemoryLimits = Field(default_factory=MemoryLimits)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    kb: KBConfig = Field(default_factory=KBConfig)

    # required blocks
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
