from __future__ import annotations

from typing import Any

from picobot.agent.models import RuntimeHooks


class ToolExecutor:
    """
    Boundary dedicato per l'esecuzione dei tool.

    Responsabilità:
    - resolve tool name
    - validate input model
    - eseguire handler
    - emettere hook started/completed/failed

    Nota:
    il seam backward-compatible verso i test resta nell'Orchestrator
    tramite _call_tool(...), che può ancora fare fallback verso
    _run_tool(tool_name, args) monkeypatchato.
    """

    def __init__(self, orchestrator) -> None:
        self.orchestrator = orchestrator

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        hooks: RuntimeHooks | None = None,
        workflow_name: str | None = None,
    ) -> dict:
        resolved = self.orchestrator.tools.resolve_name(tool_name)

        await self.orchestrator._emit_hook(
            getattr(hooks, "on_tool_started", None),
            {
                "tool_name": resolved,
                "workflow_name": workflow_name,
                "args_keys": sorted(list((args or {}).keys())),
            },
        )

        try:
            tool = self.orchestrator.tools.get(resolved)
            model = tool.validate(args or {})
            result = await tool.handler(model)
        except Exception as exc:
            await self.orchestrator._emit_hook(
                getattr(hooks, "on_tool_failed", None),
                {
                    "tool_name": resolved,
                    "workflow_name": workflow_name,
                    "error": str(exc),
                },
            )
            raise

        await self.orchestrator._emit_hook(
            getattr(hooks, "on_tool_completed", None),
            {
                "tool_name": resolved,
                "workflow_name": workflow_name,
                "ok": bool(isinstance(result, dict) and result.get("ok")),
                "has_data": bool(isinstance(result, dict) and result.get("data")),
            },
        )

        return result
