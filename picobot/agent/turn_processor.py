from __future__ import annotations

from typing import Any
import os

DEBUG_RUNTIME = os.getenv("PICOBOT_DEBUG_CLI", "0").strip().lower() in {"1", "true", "yes", "on"}


def _debug(msg: str) -> None:
    if DEBUG_RUNTIME:
        print(f"[debug][turn] {msg}")

from picobot.agent.models import RuntimeHooks, StatusCb, TurnResult
from picobot.session.manager import Session


class TurnProcessor:
    def __init__(self, orchestrator) -> None:
        self.orchestrator = orchestrator

    async def _emit_hook(self, hook, payload: dict[str, Any]) -> None:
        await self.orchestrator._emit_hook(hook, payload)

    async def process(
        self,
        *,
        session: Session,
        user_text: str,
        status: StatusCb | None = None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        text = (user_text or "").strip()
        if not text:
            return TurnResult(content="", action="noop", reason="empty input")

        if status:
            await status("🧭 Analizzo l'input e seleziono la route…")

        route = self.orchestrator.route_selector.select(
            session=session,
            user_text=text,
        )
        _debug(
            f"selected route action={route.route_action} "
            f"name={route.route_name} source={route.route_source} "
            f"score={route.route_score:.3f} kb_probe={route.kb_probe_score}"
        )
        if route.route_candidates:
            for item in route.route_candidates[:4]:
                _debug(f"candidate {item}")
        decision = route.raw_decision
        kb_name = str(session.get_state().get("kb_name") or self.orchestrator.cfg.default_kb_name or "default").strip()

        await self._emit_hook(
            getattr(hooks, "on_route_selected", None),
            {
                "route_name": route.route_name,
                "route_action": route.route_action,
                "route_reason": route.route_reason,
                "route_score": route.route_score,
                "route_candidates": route.route_candidates,
                "route_source": route.route_source,
                "kb_probe_score": route.kb_probe_score,
                "lang": route.lang,
            },
        )

        if status:
            route_label = f"{route.route_action or '?'}:{route.route_name or '?'}"
            route_source = route.route_source or "unknown"
            extra = ""
            if route.kb_probe_score is not None:
                extra = f" kb={route.kb_probe_score:.2f}"
            await status(f"🧭 Route: {route_label} [{route_source}]{extra}")

        if route.route_action == "tool":
            result = await self.orchestrator.workflow_dispatcher.explicit_tool(
                session=session,
                lang=route.lang,
                tool_name=route.route_name or "",
                args=dict(getattr(decision, "args", {}) or {}),
                status=status,
                hooks=hooks,
            )
        else:
            result = await self.orchestrator.workflow_dispatcher.dispatch(
                session=session,
                workflow_name=route.route_name or "",
                user_text=text,
                lang=route.lang,
                status=status,
                hooks=hooks,
            )

        if result.content.strip():
            self.orchestrator.memory_context_service.append_turn_memory(session, text, result.content)
            await self._emit_hook(
                getattr(hooks, "on_memory_updated", None),
                {
                    "history_appended": True,
                    "user_text_len": len(text),
                    "assistant_text_len": len(result.content),
                },
            )

        if result.audio_path:
            self.orchestrator.memory_context_service.store_audio_state(session, result.audio_path)
            await self._emit_hook(
                getattr(hooks, "on_audio_generated", None),
                {
                    "audio_path": result.audio_path,
                    "has_script": bool(result.script),
                    "workflow_name": route.route_name,
                },
            )

        result.route_name = route.route_name
        result.route_action = route.route_action
        result.route_reason = route.route_reason
        result.route_score = route.route_score
        result.route_candidates = route.route_candidates
        result.route_source = route.route_source
        result.kb_probe_score = route.kb_probe_score
        result.kb_name = kb_name

        audit = dict(result.audit or {})
        audit.setdefault("route_name", route.route_name)
        audit.setdefault("route_action", route.route_action)
        audit.setdefault("route_reason", route.route_reason)
        audit.setdefault("route_score", route.route_score)
        audit.setdefault("route_source", route.route_source)
        audit.setdefault("kb_probe_score", route.kb_probe_score)
        audit.setdefault("kb_name", kb_name)
        result.audit = audit

        return TurnResult(
            content=result.content,
            action=result.action,
            reason=route.route_reason or result.reason,
            score=route.route_score,
            retrieval_hits=result.retrieval_hits,
            audio_path=result.audio_path,
            script=result.script,
            route_name=result.route_name,
            route_action=result.route_action,
            route_reason=result.route_reason,
            route_score=result.route_score,
            route_candidates=result.route_candidates,
            route_source=result.route_source,
            provider_name=result.provider_name,
            kb_probe_score=result.kb_probe_score,
            kb_name=result.kb_name,
            audit=dict(result.audit or {}),
        )
