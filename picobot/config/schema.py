from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic.config import ConfigDict


class BaseCfgModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        validate_assignment=True,
        populate_by_name=True,
    )


def _setattr_no_validate(obj: object, name: str, value: Any) -> None:
    object.__setattr__(obj, name, value)


class LanguageConfig(BaseCfgModel):
    default: str = "it"


class KBConfig(BaseCfgModel):
    default_name: str = "default"
    auto_route_questions: bool = False
    auto_candidates: list[str] = Field(default_factory=list)


class MemoryLimitsConfig(BaseCfgModel):
    max_history_lines: int = 300
    tail_lines: int = 900


class SummaryConfig(BaseCfgModel):
    mode: str = "single"
    max_chars: int = 24000
    chunk_chars: int = 7000
    max_chunks: int = 6
    timeout_s: int = 600
    output_language: str = "auto"


class DebugConfig(BaseCfgModel):
    enabled: bool = False


class UIConfig(BaseCfgModel):
    use_emojis: bool = True
    use_prompt_toolkit: bool = True
    vi_mode: bool = False


class OllamaConfig(BaseCfgModel):
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b-instruct-q4_0"
    timeout_s: float = 600.0
    max_tokens: int = 1200
    podcast_max_tokens: int = 1800


class LLMTaskRoutingConfig(BaseCfgModel):
    chat: str = "ollama"
    router: str = "ollama"
    summary: str = "ollama"
    podcast_writer: str = "ollama"
    podcast_research: str = "ollama"
    qa: str = "ollama"


class LLMProviderConfig(BaseCfgModel):
    enabled: bool = True
    kind: str = "ollama"
    model: str = ""
    timeout_s: float = 600.0
    max_tokens: int = 1200


class LLMOllamaProviderConfig(LLMProviderConfig):
    kind: str = "ollama"
    base_url: str = "http://localhost:11434"


class LLMGeminiProviderConfig(LLMProviderConfig):
    kind: str = "gemini"
    enabled: bool = False
    api_key_env: str = "GEMINI_API_KEY"


class LLMProvidersConfig(BaseCfgModel):
    ollama: LLMOllamaProviderConfig = Field(default_factory=LLMOllamaProviderConfig)
    gemini: LLMGeminiProviderConfig = Field(default_factory=LLMGeminiProviderConfig)


class LLMConfig(BaseCfgModel):
    default_provider: str = "ollama"
    tasks: LLMTaskRoutingConfig = Field(default_factory=LLMTaskRoutingConfig)
    providers: LLMProvidersConfig = Field(default_factory=LLMProvidersConfig)


class VectorConfig(BaseCfgModel):
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    timeout_s: float = 60.0


class EmbeddingsConfig(BaseCfgModel):
    provider: str = "ollama"
    model: str = "nomic-embed-text"
    batch_size: int = 16
    enabled: bool = True


class QdrantConfig(BaseCfgModel):
    path: str = ".picobot/qdrant"
    router_collection: str = "router_index"
    docs_collection: str = "docs_index"


class RetrievalConfig(BaseCfgModel):
    enabled: bool = True
    provider: str = "qdrant"

    bm25_candidates: int = 9
    top_k: int = 3
    vector_top_k: int = 8
    final_top_k: int = 4

    max_context_chars: int = 5000
    max_embed_chars: int = 4000

    chunk_chars: int = 900
    chunk_overlap: int = 120

    bm25_k1: float = 1.2
    bm25_b: float = 0.75

    exact_match_boost: float = 0.03
    special_token_boosts: dict[str, float] = Field(default_factory=dict)


class RouterRerankerConfig(BaseCfgModel):
    enabled: bool = False
    provider: str = "none"
    model: str = ""


class RouterScoreWeightsConfig(BaseCfgModel):
    vector: float = 0.45
    bm25: float = 0.25
    rerank: float = 0.25
    priority: float = 0.05


class RouterConfig(BaseCfgModel):
    enabled: bool = True
    top_k: int = 5
    accept_threshold: float = 0.72
    margin: float = 0.05
    kb_probe_top_k: int = 2
    kb_probe_threshold: float = 0.55
    score_weights: RouterScoreWeightsConfig = Field(default_factory=RouterScoreWeightsConfig)
    reranker: RouterRerankerConfig = Field(default_factory=RouterRerankerConfig)


class WebSearchConfig(BaseCfgModel):
    enabled: bool = True
    backend: str = "searxng"
    searxng_url: str = "http://localhost:8080"
    timeout_s: float = 10.0
    max_results: int = 5
    managed_backend: bool = True
    health_timeout_s: float = 2.5
    startup_timeout_s: float = 45.0
    docker_compose_dir: str = "searxng"
    docker_service_name: str = "searxng"
    auto_restart_on_failure: bool = True


class ToolsBinsConfig(BaseCfgModel):
    ytdlp: str = "yt-dlp"
    ffmpeg: str = "ffmpeg"
    whisper_cpp_cli: str = "whisper-cli"
    piper: str = "piper"
    arecord: str = "arecord"
    aplay: str = "aplay"


class ToolsModelsConfig(BaseCfgModel):
    whisper_cpp: str = ""
    piper_it: str = ""
    piper_en: str = ""


class ToolsRuntimeConfig(BaseCfgModel):
    mode: str = "docker"


class ToolsWhisperConfig(BaseCfgModel):
    model: str = "/opt/picobot/models/whisper/ggml-small.bin"


class ToolsPiperConfig(BaseCfgModel):
    installed_voices: list[str] = Field(default_factory=lambda: [
        "it_IT-paola-medium",
        "it_IT-aurora-medium",
        "en_US-lessac-medium",
        "en_US-amy-medium",
        "en_US-ryan-high",
    ])
    default_voice_by_lang: dict[str, str] = Field(default_factory=lambda: {
        "it": "it_IT-paola-medium",
        "en": "en_US-lessac-medium",
    })
    models_dir: str = "/opt/picobot/models/piper"
    custom_voice_urls: dict[str, dict[str, str]] = Field(default_factory=dict)
    voices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_voices_alias(self) -> "ToolsPiperConfig":
        if not self.voices and self.installed_voices:
            _setattr_no_validate(self, "voices", list(self.installed_voices))
        elif not self.installed_voices and self.voices:
            _setattr_no_validate(self, "installed_voices", list(self.voices))
        return self


class ToolsSandboxExecConfig(BaseCfgModel):
    enabled: bool = True
    timeout_s: int = 180
    max_output_bytes: int = 200000
    allowed_bins: list[str] = Field(default_factory=lambda: [
        "yt-dlp",
        "ffmpeg",
        "piper",
        "whisper-cli",
        "python",
        "bash",
    ])


class ToolsYouTubeConfig(BaseCfgModel):
    enabled: bool = True
    timeout_s: int = 180
    ytdlp_args: list[str] = Field(default_factory=list)
    prefer_sub_langs: list[str] = Field(default_factory=lambda: ["it", "en"])


class ToolsConfig(BaseCfgModel):
    runtime: ToolsRuntimeConfig = Field(default_factory=ToolsRuntimeConfig)
    bins: ToolsBinsConfig = Field(default_factory=ToolsBinsConfig)
    models: ToolsModelsConfig = Field(default_factory=ToolsModelsConfig)
    whisper: ToolsWhisperConfig = Field(default_factory=ToolsWhisperConfig)
    piper: ToolsPiperConfig = Field(default_factory=ToolsPiperConfig)
    sandbox_exec: ToolsSandboxExecConfig = Field(default_factory=ToolsSandboxExecConfig)
    youtube: ToolsYouTubeConfig = Field(default_factory=ToolsYouTubeConfig)

    ytdlp_bin: str = ""
    ytdlp_args: list[str] = Field(default_factory=list)

    ffmpeg_bin: str = "ffmpeg"
    arecord_bin: str = "arecord"
    aplay_bin: str = "aplay"

    whisper_cpp_cli: str = ""
    whisper_cpp_main_path: str = ""
    whisper_cpp_dir: str = ""
    whisper_model: str = ""
    whisper_language: str = "auto"

    piper_bin: str = ""
    piper_model_it: str = ""
    piper_model_en: str = ""

    @model_validator(mode="after")
    def _sync_legacy_and_nested(self) -> "ToolsConfig":
        if not self.ytdlp_bin and self.bins.ytdlp:
            _setattr_no_validate(self, "ytdlp_bin", self.bins.ytdlp)
        if not self.ffmpeg_bin and self.bins.ffmpeg:
            _setattr_no_validate(self, "ffmpeg_bin", self.bins.ffmpeg)
        if not self.arecord_bin and self.bins.arecord:
            _setattr_no_validate(self, "arecord_bin", self.bins.arecord)
        if not self.aplay_bin and self.bins.aplay:
            _setattr_no_validate(self, "aplay_bin", self.bins.aplay)
        if not self.piper_bin and self.bins.piper:
            _setattr_no_validate(self, "piper_bin", self.bins.piper)
        if not self.whisper_cpp_cli and self.bins.whisper_cpp_cli:
            _setattr_no_validate(self, "whisper_cpp_cli", self.bins.whisper_cpp_cli)

        if not self.whisper_model:
            if self.whisper.model:
                _setattr_no_validate(self, "whisper_model", self.whisper.model)
            elif self.models.whisper_cpp:
                _setattr_no_validate(self, "whisper_model", self.models.whisper_cpp)

        if not self.piper_model_it and self.models.piper_it:
            _setattr_no_validate(self, "piper_model_it", self.models.piper_it)
        if not self.piper_model_en and self.models.piper_en:
            _setattr_no_validate(self, "piper_model_en", self.models.piper_en)

        if not self.bins.ytdlp and self.ytdlp_bin:
            _setattr_no_validate(self.bins, "ytdlp", self.ytdlp_bin)
        if not self.bins.ffmpeg and self.ffmpeg_bin:
            _setattr_no_validate(self.bins, "ffmpeg", self.ffmpeg_bin)
        if not self.bins.arecord and self.arecord_bin:
            _setattr_no_validate(self.bins, "arecord", self.arecord_bin)
        if not self.bins.aplay and self.aplay_bin:
            _setattr_no_validate(self.bins, "aplay", self.aplay_bin)
        if not self.bins.piper and self.piper_bin:
            _setattr_no_validate(self.bins, "piper", self.piper_bin)
        if not self.bins.whisper_cpp_cli and self.whisper_cpp_cli:
            _setattr_no_validate(self.bins, "whisper_cpp_cli", self.whisper_cpp_cli)

        if not self.models.whisper_cpp and self.whisper_model:
            _setattr_no_validate(self.models, "whisper_cpp", self.whisper_model)
        if not self.whisper.model and self.whisper_model:
            _setattr_no_validate(self.whisper, "model", self.whisper_model)

        if not self.models.piper_it and self.piper_model_it:
            _setattr_no_validate(self.models, "piper_it", self.piper_model_it)
        if not self.models.piper_en and self.piper_model_en:
            _setattr_no_validate(self.models, "piper_en", self.piper_model_en)

        if not self.ytdlp_args and self.youtube.ytdlp_args:
            _setattr_no_validate(self, "ytdlp_args", list(self.youtube.ytdlp_args))
        if not self.youtube.ytdlp_args and self.ytdlp_args:
            _setattr_no_validate(self.youtube, "ytdlp_args", list(self.ytdlp_args))

        return self


class SandboxExecPolicyConfig(BaseCfgModel):
    enabled: bool = True
    timeout_s: int = 180
    max_output_bytes: int = 200000
    allowed_bins: list[str] = Field(default_factory=list)


class SandboxFileConfig(BaseCfgModel):
    enabled: bool = True
    root: str = ".picobot/workspace"
    max_bytes: int = 200000


class SandboxPythonConfig(BaseCfgModel):
    enabled: bool = True
    timeout_s: int = 5
    cwd: str = ".picobot/workspace"
    no_network: bool = True


class SandboxWebConfig(BaseCfgModel):
    enabled: bool = True
    timeout_s: int = 10
    max_bytes: int = 200000
    whitelist_domains: list[str] = Field(default_factory=list)


class SandboxRuntimeDockerConfig(BaseCfgModel):
    enabled: bool = True
    image: str = "picobot-sandbox:latest"
    container_name: str = "picobot-sandbox"
    docker_bin: str = "docker"
    container_workspace_root: str = "/workspace"
    auto_create: bool = True
    extra_run_args: list[str] = Field(default_factory=list)


class SandboxRuntimeConfig(BaseCfgModel):
    backend: str = "local"
    workspace_root: str = ".picobot/workspace"
    runs_dir: str = ".picobot/workspace/sandbox_runs"
    docker: SandboxRuntimeDockerConfig = Field(default_factory=SandboxRuntimeDockerConfig)


class SandboxConfig(BaseCfgModel):
    runtime: SandboxRuntimeConfig = Field(default_factory=SandboxRuntimeConfig)
    file: SandboxFileConfig = Field(default_factory=SandboxFileConfig)
    python: SandboxPythonConfig = Field(default_factory=SandboxPythonConfig)
    web: SandboxWebConfig = Field(default_factory=SandboxWebConfig)
    exec: SandboxExecPolicyConfig = Field(default_factory=SandboxExecPolicyConfig)


class TelegramConfig(BaseCfgModel):
    enabled: bool = False
    bot_token: str = ""
    kb_per_chat: bool = True
    pdf_auto_ingest: bool = True
    stt_auto: bool = True
    voice_stt_enabled: bool = False
    send_transcript_flag: bool = False
    echo_transcript: bool = False
    max_voice_seconds: int = 240
    debug_terminal: bool = True


class PodcastVoiceConfig(BaseCfgModel):
    voice_id: str = ""


class PodcastRoleVoicesConfig(BaseCfgModel):
    narrator: PodcastVoiceConfig = Field(default_factory=PodcastVoiceConfig)
    expert: PodcastVoiceConfig = Field(default_factory=PodcastVoiceConfig)


class PodcastVoicesConfig(BaseCfgModel):
    it: PodcastRoleVoicesConfig = Field(default_factory=PodcastRoleVoicesConfig)
    en: PodcastRoleVoicesConfig = Field(default_factory=PodcastRoleVoicesConfig)


class PodcastTriggersConfig(BaseCfgModel):
    it: list[str] = Field(default_factory=lambda: [
        "voglio un podcast su",
        "fammi un podcast su",
    ])
    en: list[str] = Field(default_factory=lambda: [
        "i want a podcast about",
        "make a podcast about",
    ])


class PodcastConfig(BaseCfgModel):
    enabled: bool = True
    tts_backend: str = "piper"
    audio_format: str = "mp3"
    default_minutes: int = 1
    max_minutes: int = 2
    target_words_per_minute: int = 150
    send_script_text: bool = False
    output_dir: str = "outputs/podcasts"
    triggers: PodcastTriggersConfig = Field(default_factory=PodcastTriggersConfig)
    voices: PodcastVoicesConfig = Field(default_factory=PodcastVoicesConfig)


class Config(BaseCfgModel):
    workspace: str = ".picobot/workspace"

    default_language: str = "it"
    default_kb_name: str = "default"

    language: LanguageConfig = Field(default_factory=LanguageConfig)
    kb: KBConfig = Field(default_factory=KBConfig)

    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    vector: VectorConfig = Field(default_factory=VectorConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)

    memory_limits: MemoryLimitsConfig = Field(default_factory=MemoryLimitsConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)

    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)

    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)

    ui: UIConfig = Field(default_factory=UIConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    podcast: PodcastConfig = Field(default_factory=PodcastConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)

    @model_validator(mode="after")
    def _sync_everything(self) -> "Config":
        if self.language.default:
            _setattr_no_validate(self, "default_language", self.language.default)
        else:
            _setattr_no_validate(self.language, "default", self.default_language)

        if self.kb.default_name:
            _setattr_no_validate(self, "default_kb_name", self.kb.default_name)
        else:
            _setattr_no_validate(self.kb, "default_name", self.default_kb_name)

        if not self.embeddings.provider and self.vector.provider:
            _setattr_no_validate(self.embeddings, "provider", self.vector.provider)
        if not self.embeddings.model and self.vector.embed_model:
            _setattr_no_validate(self.embeddings, "model", self.vector.embed_model)

        if not self.vector.provider and self.embeddings.provider:
            _setattr_no_validate(self.vector, "provider", self.embeddings.provider)
        if not self.vector.embed_model and self.embeddings.model:
            _setattr_no_validate(self.vector, "embed_model", self.embeddings.model)

        if not self.vector.base_url and self.ollama.base_url:
            _setattr_no_validate(self.vector, "base_url", self.ollama.base_url)

        if not self.sandbox.exec.allowed_bins and self.tools.sandbox_exec.allowed_bins:
            _setattr_no_validate(self.sandbox.exec, "allowed_bins", list(self.tools.sandbox_exec.allowed_bins))

        # sync legacy ollama -> llm.providers.ollama
        llm_ollama = self.llm.providers.ollama
        if not llm_ollama.base_url and self.ollama.base_url:
            _setattr_no_validate(llm_ollama, "base_url", self.ollama.base_url)
        if not llm_ollama.model and self.ollama.model:
            _setattr_no_validate(llm_ollama, "model", self.ollama.model)
        if not llm_ollama.timeout_s and self.ollama.timeout_s:
            _setattr_no_validate(llm_ollama, "timeout_s", self.ollama.timeout_s)
        if not llm_ollama.max_tokens and self.ollama.max_tokens:
            _setattr_no_validate(llm_ollama, "max_tokens", self.ollama.max_tokens)

        if self.ollama.base_url:
            _setattr_no_validate(llm_ollama, "base_url", self.ollama.base_url)
        if self.ollama.model:
            _setattr_no_validate(llm_ollama, "model", self.ollama.model)
        if self.ollama.timeout_s:
            _setattr_no_validate(llm_ollama, "timeout_s", self.ollama.timeout_s)
        if self.ollama.max_tokens:
            _setattr_no_validate(llm_ollama, "max_tokens", self.ollama.max_tokens)

        _setattr_no_validate(self, "workspace", str(Path(self.workspace).expanduser()))
        _setattr_no_validate(self.qdrant, "path", str(Path(self.qdrant.path).expanduser()))
        _setattr_no_validate(self.podcast, "output_dir", str(Path(self.podcast.output_dir).expanduser()))
        _setattr_no_validate(self.sandbox.file, "root", str(Path(self.sandbox.file.root).expanduser()))
        _setattr_no_validate(self.sandbox.python, "cwd", str(Path(self.sandbox.python.cwd).expanduser()))
        _setattr_no_validate(self.sandbox.runtime, "workspace_root", str(Path(self.sandbox.runtime.workspace_root).expanduser()))
        _setattr_no_validate(self.sandbox.runtime, "runs_dir", str(Path(self.sandbox.runtime.runs_dir).expanduser()))

        if self.tools.whisper_cpp_main_path:
            _setattr_no_validate(self.tools, "whisper_cpp_main_path", str(Path(self.tools.whisper_cpp_main_path).expanduser()))
        if self.tools.whisper_cpp_dir:
            _setattr_no_validate(self.tools, "whisper_cpp_dir", str(Path(self.tools.whisper_cpp_dir).expanduser()))
        if self.tools.whisper_model:
            _setattr_no_validate(self.tools, "whisper_model", str(Path(self.tools.whisper_model).expanduser()))
        if self.tools.piper_model_it:
            _setattr_no_validate(self.tools, "piper_model_it", str(Path(self.tools.piper_model_it).expanduser()))
        if self.tools.piper_model_en:
            _setattr_no_validate(self.tools, "piper_model_en", str(Path(self.tools.piper_model_en).expanduser()))

        return self

    def as_runtime_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")


Language = LanguageConfig
KB = KBConfig
MemoryLimits = MemoryLimitsConfig
Summary = SummaryConfig
Debug = DebugConfig
UI = UIConfig
Ollama = OllamaConfig
LLM = LLMConfig
Vector = VectorConfig
Embeddings = EmbeddingsConfig
Qdrant = QdrantConfig
Retrieval = RetrievalConfig
Router = RouterConfig
WebSearch = WebSearchConfig
Tools = ToolsConfig
Sandbox = SandboxConfig
Telegram = TelegramConfig
Podcast = PodcastConfig
