from __future__ import annotations

from picobot.config.schema import Config
from picobot.providers.base import ChatProvider
from picobot.providers.gemini import GeminiProvider
from picobot.providers.ollama import OllamaProvider


class ProviderRegistry:
    def __init__(self, providers: dict[str, ChatProvider]) -> None:
        self._providers = dict(providers)

    def get(self, name: str) -> ChatProvider:
        key = str(name or "").strip()
        if not key:
            raise KeyError("provider name is empty")
        if key not in self._providers:
            raise KeyError(f"provider not registered: {key}")
        return self._providers[key]

    def has(self, name: str) -> bool:
        key = str(name or "").strip()
        return bool(key) and key in self._providers

    def names(self) -> list[str]:
        return sorted(self._providers.keys())


def build_provider_registry(cfg: Config) -> ProviderRegistry:
    providers: dict[str, ChatProvider] = {}

    ollama_cfg = cfg.llm.providers.ollama
    if ollama_cfg.enabled:
        providers["ollama"] = OllamaProvider(
            base_url=ollama_cfg.base_url,
            model=ollama_cfg.model,
            timeout_s=ollama_cfg.timeout_s,
            default_max_tokens=ollama_cfg.max_tokens,
        )

    gemini_cfg = cfg.llm.providers.gemini
    if gemini_cfg.enabled:
        providers["gemini"] = GeminiProvider(
            model=gemini_cfg.model,
            api_key_env=gemini_cfg.api_key_env,
            timeout_s=gemini_cfg.timeout_s,
            default_max_tokens=gemini_cfg.max_tokens,
        )

    return ProviderRegistry(providers)
