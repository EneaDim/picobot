from __future__ import annotations

from picobot.config.schema import Config
from picobot.providers.registry import ProviderRegistry


class ProviderPolicyError(Exception):
    pass


def provider_name_for_task(cfg: Config, task_name: str) -> str:
    task = str(task_name or "").strip()
    if not task:
        return str(cfg.llm.default_provider or "ollama")

    tasks = cfg.llm.tasks

    mapping = {
        "chat": tasks.chat,
        "router": tasks.router,
        "summary": tasks.summary,
        "podcast_writer": tasks.podcast_writer,
        "podcast_research": tasks.podcast_research,
        "qa": tasks.qa,
    }

    return str(mapping.get(task) or cfg.llm.default_provider or "ollama")


def provider_for_task(cfg: Config, registry: ProviderRegistry, task_name: str):
    name = provider_name_for_task(cfg, task_name)
    if not registry.has(name):
        raise ProviderPolicyError(f"provider '{name}' configured for task '{task_name}' but not registered")
    return registry.get(name)
