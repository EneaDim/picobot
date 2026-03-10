from __future__ import annotations

from pathlib import Path

from picobot.bus.events import BusMessage, InboundMessage
from picobot.runtime.event_publisher import RuntimeEventPublisher
from picobot.session.manager import SessionManager


class HeartbeatHandler:
    """
    Handler dedicato per inbound.heartbeat_tick.

    Per ora produce uno snapshot runtime minimale ma strutturato.
    In seguito può essere esteso con:
    - health checks provider
    - stato sandbox docker
    - stato backend search
    - metriche runtime
    """

    def __init__(
        self,
        *,
        events: RuntimeEventPublisher,
        workspace: Path,
        session_manager: SessionManager,
        orchestrator_name: str = "Orchestrator",
    ) -> None:
        self.events = events
        self.workspace = Path(workspace).expanduser().resolve()
        self.session_manager = session_manager
        self.orchestrator_name = orchestrator_name
        self.runtime_started = False

    def bind_runtime_state(self, *, runtime_started: bool) -> None:
        self.runtime_started = bool(runtime_started)

    async def handle(self, message: BusMessage) -> None:
        if not isinstance(message, InboundMessage):
            return

        await self.events.publish_heartbeat_snapshot(
            inbound=message,
            runtime_started=self.runtime_started,
            workspace=str(self.workspace),
            session_manager_name=self.session_manager.__class__.__name__,
            orchestrator_name=self.orchestrator_name,
        )
