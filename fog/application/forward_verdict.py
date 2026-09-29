"""ForwardVerdictToClient — caso de uso: espera el veredicto de Cloud
(VerdictStreamSubscriberPort) y lo guarda/reenvía al front por WebSocket si
ya está conectado. Mirror de `_wait_for_verdict` del fog/main.py anterior,
ahora desacoplado de redis.asyncio directo.
"""

from __future__ import annotations

import logging

from fog.domain.models import UnavailableResult
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from fog.ports.verdict_subscriber import VerdictStreamSubscriberPort

log = logging.getLogger("fog.application")


class ForwardVerdictToClient:
    def __init__(self, subscriber: VerdictStreamSubscriberPort, sessions: SessionRegistry):
        self._subscriber = subscriber
        self._sessions = sessions

    async def execute(self, revision_id: str) -> None:
        """Espera el resultado de Cloud para la revisión y lo entrega a su sesión.

        Args:
            revision_id: revisión cuyo veredicto se espera.
        """
        resultado = await self._subscriber.wait_for_verdict(revision_id)

        session = self._sessions.get(revision_id)
        if session is None:
            log.warning("[%s] veredicto recibido pero la sesión ya no existe", revision_id)
            return

        if isinstance(resultado, UnavailableResult):
            await session.set_unavailable(resultado)
        else:
            await session.set_verdict(resultado)
        if session.ws is not None:
            await session.ws.send_json(resultado.to_ws_message())
