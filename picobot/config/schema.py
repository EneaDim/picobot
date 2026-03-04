from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, AliasChoices, model_validator
from pydantic.config import ConfigDict


# ----------------------------
# Core small blocks
# ----------------------------

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
    # Legacy/extra signals (kept)
    auto_candidates: list[str] = Field(default_factory=list)

    # New (optional)
    default_name: str | None = None
    auto_route_questions: bool = False


class LanguageConfig(BaseModel):
    default: str = "it"


class EmbeddingsConfig(BaseModel):
    enabled: bool = False
    model: str = "nomic-embed-text:latest"


class SummarizerConfig(BaseModel):
    model: str = "qwen2.5:3b-instruct-q4_0"


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

    # Legacy flags (kept for backward compatibility)
    voice_stt_enabled: bool = True
    echo_transcript: bool = False

    # New flags for richer Telegram automations
    kb_per_chat: bool = True
    pdf_auto_ingest: bool = True
    stt_auto: bool = True
    max_voice_seconds: int = 240
    send_transcript_flag: bool = False
    debug_terminal: bool = False


# ----------------------------
# Tools (new structured + legacy-friendly)
# ----------------------------

class ToolsBins(BaseModel):
    ytdlp: str = ""
    ffmpeg: str = "ffmpeg"
    arecord: str = "arecord"
    aplay: str = "aplay"
    whisper_cpp_cli: str = ""
    piper: str = ""
    qwen_tts: str = ""


class ToolsModels(BaseModel):
    whisper_cpp: str = ""
    piper_it: str = ""
    piper_en: str = ""
    qwen_tts_dir: str = ""


class ToolsVoices(BaseModel):
    piper_voices_dir: str = ""
    piper_voices_official: str = ""
    piper_voices_hf: str = ""


class SandboxExecConfig(BaseModel):
    enabled: bool = True
    timeout_s: int = 180
    max_output_bytes: int = 200_000
    allowed_bins: list[str] = Field(default_factory=list)


class YouTubeToolConfig(BaseModel):
    enabled: bool = True
    timeout_s: int = 180
    ytdlp_args: list[str] = Field(default_factory=list)
    prefer_sub_langs: list[str] = Field(default_factory=lambda: ["it", "en"])


class ToolsConfig(BaseModel):
    """
    Backward-compatible:
    - supports legacy flat keys (ytdlp_bin, ffmpeg_bin, piper_model_it, ...)
    - supports new structured keys (bins/models/voices/sandbox_exec/youtube)
    Code can continue to use cfg.tools.ytdlp_bin, etc.
    """
    model_config = ConfigDict(extra="ignore")

    # --- legacy flat fields (kept) ---
    base_dir: str = ""
    whisper_cpp_dir: str = ""
    whisper_model: str = ""
    whisper_language: str = "auto"
    ytdlp_bin: str = ""
    ytdlp_args: list[str] = Field(default_factory=list)
    ffmpeg_bin: str = "ffmpeg"
    arecord_bin: str = "arecord"
    aplay_bin: str = "aplay"
    piper_bin: str = ""
    piper_model_it: str = ""
    piper_model_en: str = ""
    piper_voices_dir: str = ""
    piper_voices_official: str = ""
    piper_voices_hf: str = ""
    qwen_tts_bin: str = ""
    qwen_tts_model_dir: str = ""
    whisper_cpp_main_path: str = "./whisper.cpp/main"

    # --- new structured blocks ---
    bins: ToolsBins = Field(default_factory=ToolsBins)
    models: ToolsModels = Field(default_factory=ToolsModels)
    voices: ToolsVoices = Field(default_factory=ToolsVoices)
    sandbox_exec: SandboxExecConfig = Field(default_factory=SandboxExecConfig)
    youtube: YouTubeToolConfig = Field(default_factory=YouTubeToolConfig)

    @model_validator(mode="after")
    def _sync_new_to_legacy(self) -> "ToolsConfig":
        # If new config is set, populate legacy fields when empty
        if not self.ytdlp_bin and self.bins.ytdlp:
            self.ytdlp_bin = self.bins.ytdlp
        if not self.ffmpeg_bin and self.bins.ffmpeg:
            self.ffmpeg_bin = self.bins.ffmpeg
        if not self.arecord_bin and self.bins.arecord:
            self.arecord_bin = self.bins.arecord
        if not self.aplay_bin and self.bins.aplay:
            self.aplay_bin = self.bins.aplay
        if not self.piper_bin and self.bins.piper:
            self.piper_bin = self.bins.piper
        if not self.qwen_tts_bin and self.bins.qwen_tts:
            self.qwen_tts_bin = self.bins.qwen_tts

        if not self.whisper_model and self.models.whisper_cpp:
            self.whisper_model = self.models.whisper_cpp
        if not self.piper_model_it and self.models.piper_it:
            self.piper_model_it = self.models.piper_it
        if not self.piper_model_en and self.models.piper_en:
            self.piper_model_en = self.models.piper_en
        if not self.qwen_tts_model_dir and self.models.qwen_tts_dir:
            self.qwen_tts_model_dir = self.models.qwen_tts_dir

        if not self.piper_voices_dir and self.voices.piper_voices_dir:
            self.piper_voices_dir = self.voices.piper_voices_dir
        if not self.piper_voices_official and self.voices.piper_voices_official:
            self.piper_voices_official = self.voices.piper_voices_official
        if not self.piper_voices_hf and self.voices.piper_voices_hf:
            self.piper_voices_hf = self.voices.piper_voices_hf

        # youtube args: if legacy empty, copy from new block (and vice versa)
        if not self.ytdlp_args and self.youtube.ytdlp_args:
            self.ytdlp_args = list(self.youtube.ytdlp_args)
        if not self.youtube.ytdlp_args and self.ytdlp_args:
            self.youtube.ytdlp_args = list(self.ytdlp_args)

        return self


# ----------------------------
# Retrieval / Web / Podcast / Debug
# ----------------------------

class RetrievalConfig(BaseModel):
    enabled: bool = True

    bm25_candidates: int = 12
    top_k: int = 3
    max_embed_chars: int = 4000
    max_context_chars: int = 5000

    chunk_chars: int = 900
    chunk_overlap: int = 120
    bm25_k1: float = 1.5
    bm25_b: float = 0.75


class WebConfig(BaseModel):
    # Web SEARCH (local engine, e.g. SearXNG)
    enabled: bool = False
    searxng_url: str = "http://localhost:8080"
    timeout_s: float = 10.0
    max_results: int = 5


class PodcastTriggers(BaseModel):
    it: list[str] = Field(default_factory=lambda: ["voglio un podcast su", "fammi un podcast su"])
    en: list[str] = Field(default_factory=lambda: ["i want a podcast about", "make a podcast about"])


class PodcastVoice(BaseModel):
    voice_id: str = ""


class PodcastVoicesLang(BaseModel):
    narrator: PodcastVoice = Field(default_factory=PodcastVoice)
    expert: PodcastVoice = Field(default_factory=PodcastVoice)


class PodcastVoices(BaseModel):
    it: PodcastVoicesLang = Field(default_factory=PodcastVoicesLang)
    en: PodcastVoicesLang = Field(default_factory=PodcastVoicesLang)


class PodcastConfig(BaseModel):
    enabled: bool = False
    tts_backend: str = "piper"
    audio_format: str = "mp3"

    default_minutes: int = 1
    max_minutes: int = 2
    target_words_per_minute: int = 150

    send_script_text: bool = False
    output_dir: str = "outputs/podcasts"

    triggers: PodcastTriggers = Field(default_factory=PodcastTriggers)
    voices: PodcastVoices = Field(default_factory=PodcastVoices)


class DebugConfig(BaseModel):
    enabled: bool = False


# ----------------------------
# Sandbox block (new)
# ----------------------------

class SandboxWebConfig(BaseModel):
    enabled: bool = False
    timeout_s: int = 10
    max_bytes: int = 200_000
    whitelist_domains: list[str] = Field(default_factory=list)


class SandboxFileConfig(BaseModel):
    enabled: bool = True
    root: str = ".picobot/workspace"
    max_bytes: int = 200_000


class SandboxPythonConfig(BaseModel):
    enabled: bool = True
    timeout_s: int = 5
    cwd: str = ".picobot/workspace"
    no_network: bool = True


class SandboxConfig(BaseModel):
    web: SandboxWebConfig = Field(default_factory=SandboxWebConfig)
    file: SandboxFileConfig = Field(default_factory=SandboxFileConfig)
    python: SandboxPythonConfig = Field(default_factory=SandboxPythonConfig)


# ----------------------------
# Top-level config
# ----------------------------

class Config(BaseModel):
    """
    Block-based config, legacy-friendly.
    Accepts both:
    - legacy flat keys (default_language, default_kb_name, use_embeddings, embedding_model, summarizer_model, tools.ytdlp_bin, ...)
    - new structured keys (language.default, kb.default_name, embeddings.enabled, embeddings.model, summarizer.model, tools.bins.*, tools.youtube.*, sandbox.*)
    """
    model_config = ConfigDict(extra="ignore")

    workspace: str = str(Path.home() / ".picobot" / "workspace")

    # Legacy top-level fields (still used across code/tests)
    default_kb_name: str = Field(
        default="default",
        validation_alias=AliasChoices("default_kb_name", "kb.default_name"),
    )
    default_language: str = Field(
        default="it",
        validation_alias=AliasChoices("default_language", "language.default"),
    )

    use_embeddings: bool = Field(
        default=False,
        validation_alias=AliasChoices("use_embeddings", "embeddings.enabled"),
    )
    embedding_model: str = Field(
        default="nomic-embed-text:latest",
        validation_alias=AliasChoices("embedding_model", "embeddings.model"),
    )
    summarizer_model: str = Field(
        default="qwen2.5:3b-instruct-q4_0",
        validation_alias=AliasChoices("summarizer_model", "summarizer.model"),
    )

    # Blocks
    language: LanguageConfig = Field(default_factory=LanguageConfig)
    kb: KBConfig = Field(default_factory=KBConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    summarizer: SummarizerConfig = Field(default_factory=SummarizerConfig)

    memory_limits: MemoryLimits = Field(default_factory=MemoryLimits)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)

    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    podcast: PodcastConfig = Field(default_factory=PodcastConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)

    @model_validator(mode="after")
    def _sync_top_level_and_blocks(self) -> "Config":
        # Keep blocks aligned with legacy top-level
        if self.language and (self.language.default != self.default_language):
            self.language.default = self.default_language

        if self.kb:
            if self.kb.default_name is None:
                self.kb.default_name = self.default_kb_name
            if self.default_kb_name != (self.kb.default_name or self.default_kb_name):
                self.default_kb_name = self.kb.default_name or self.default_kb_name

        if self.embeddings:
            self.embeddings.enabled = bool(self.use_embeddings)
            if self.embedding_model:
                self.embeddings.model = self.embedding_model

        if self.summarizer and self.summarizer_model:
            self.summarizer.model = self.summarizer_model

        return self
