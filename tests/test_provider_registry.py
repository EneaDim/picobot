from picobot.config.schema import Config
from picobot.providers.policy import provider_name_for_task
from picobot.providers.registry import build_provider_registry


def test_provider_registry_builds_ollama_by_default():
    cfg = Config()
    registry = build_provider_registry(cfg)

    assert registry.has("ollama") is True
    assert "ollama" in registry.names()


def test_provider_registry_can_enable_gemini():
    cfg = Config()
    cfg.llm.providers.gemini.enabled = True
    cfg.llm.providers.gemini.model = "gemini-2.5-flash"

    registry = build_provider_registry(cfg)

    assert registry.has("ollama") is True
    assert registry.has("gemini") is True
    assert "gemini" in registry.names()


def test_provider_policy_uses_task_mapping():
    cfg = Config()
    cfg.llm.default_provider = "ollama"
    cfg.llm.tasks.chat = "ollama"
    cfg.llm.tasks.summary = "gemini"
    cfg.llm.tasks.podcast_writer = "gemini"

    assert provider_name_for_task(cfg, "chat") == "ollama"
    assert provider_name_for_task(cfg, "summary") == "gemini"
    assert provider_name_for_task(cfg, "podcast_writer") == "gemini"
    assert provider_name_for_task(cfg, "unknown_task") == "ollama"
