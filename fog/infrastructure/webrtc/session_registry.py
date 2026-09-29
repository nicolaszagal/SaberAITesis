"""SessionRegistry — estado de runtime por revisión (RTCPeerConnection,
websocket del front, señal de luz, evento de veredicto). No es el
dominio: `Match` (fog/domain/models.py) es la entidad persistible; esto es
infraestructura de sesión en memoria del proceso de Fog mientras dura el
clip, equivalente al dict global `MATCHES` del fog/main.py anterior pero
encapsulado para que composition.py controle su ciclo de vida.

Un combate admite N revisiones (un clip cada una): la sesión se identifica
por `revision_id`, no por `match_id`, para que dos clips del mismo combate
tengan veredictos y WebSockets independientes.

Ya no buffer-ea los frames recibidos (antes `self.frames: list[np.ndarray]`)
— track_consumer.py los procesa frame a frame contra un
PoseTrackingSession propio en cuanto llegan, en vez de acumularlos aquí
para procesarlos todos juntos al final del clip.

DEF-16: antes `remove()` nunca se invocaba, así que las sesiones (y su
RTCPeerConnection) se acumulaban para siempre. Ahora `MatchSession` cierra
su `pc` y se marca `closed_at` en cuanto se entrega el veredicto o el "no
disponible" (`set_verdict`/`set_unavailable`), y `sweep_expired`/
`sweep_forever` liberan las sesiones cerradas hace más de SESSION_TTL_S —
la demora entre "cerrada" y "liberada" es la ventana para que una
conexión tardía de GET /ws/veredicto/{revision_id} todavía encuentre el
resultado.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from aiortc import RTCPeerConnection

from fog.domain.models import LuzSignal, UnavailableResult, VerdictView, WeaponSide


class MatchSession:
    def __init__(
        self,
        match_id: str,
        revision_id: str,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.match_id = match_id
        self.revision_id = revision_id
        self.weapon_side_a = weapon_side_a
        self.weapon_side_b = weapon_side_b
        self.pc: RTCPeerConnection | None = None
        self.ws = None  # fastapi.WebSocket, asignado por GET /ws/veredicto/{revision_id}
        self.luz: LuzSignal | None = None
        self.luz_event = asyncio.Event()
        # Instante del tocado en ms (RF-02, DEF-14). Se persiste en `tocado`
        # (D03); no se usa para recortar el clip.
        self.t_tocado_ms: int | None = None
        self.verdict: VerdictView | None = None
        self.verdict_event = asyncio.Event()
        self.unavailable: UnavailableResult | None = None
        self.unavailable_event = asyncio.Event()
        self._clock = clock
        # Instante (self._clock()) en que se entregó el veredicto o el "no
        # disponible". None mientras la sesión sigue en curso: sweep_expired
        # nunca libera una sesión que todavía no terminó (DEF-16).
        self.closed_at: float | None = None

    def set_luz(self, luz: LuzSignal) -> None:
        self.luz = luz
        self.luz_event.set()

    async def set_verdict(self, verdict: VerdictView) -> None:
        self.verdict = verdict
        self.verdict_event.set()
        await self._close()

    async def set_unavailable(self, result: UnavailableResult) -> None:
        self.unavailable = result
        self.unavailable_event.set()
        await self._close()

    async def _close(self) -> None:
        if self.pc is not None:
            await self.pc.close()
        self.closed_at = self._clock()


class SessionRegistry:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._sessions: dict[str, MatchSession] = {}
        self._clock = clock

    def create(
        self,
        match_id: str,
        revision_id: str,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
    ) -> MatchSession:
        """Crea la sesión de una revisión.

        Args:
            match_id: combate al que pertenece la revisión.
            revision_id: revisión (clave de la sesión).
            weapon_side_a: brazo armado del tirador A.
            weapon_side_b: brazo armado del tirador B.

        Returns:
            La sesión creada y registrada.
        """
        session = MatchSession(
            match_id, revision_id, weapon_side_a, weapon_side_b, clock=self._clock
        )
        self._sessions[revision_id] = session
        return session

    def get(self, revision_id: str) -> MatchSession | None:
        return self._sessions.get(revision_id)

    def latest_for_match(self, match_id: str) -> MatchSession | None:
        """Sesión más reciente del combate.

        Solo la usa `POST /webrtc/{match_id}/luz`: el flujo WebRTC no
        persiste revisiones y su señal de luz llega por combate. No se
        usa para dirigir veredictos (van por `revision_id`).

        Returns:
            La última sesión creada para `match_id`, o None si no hay.
        """
        for session in reversed(list(self._sessions.values())):
            if session.match_id == match_id:
                return session
        return None

    def remove(self, revision_id: str) -> None:
        self._sessions.pop(revision_id, None)

    def sweep_expired(self, ttl_s: float) -> list[str]:
        """Libera las sesiones cerradas (con veredicto o "no disponible"
        ya entregado) hace más de `ttl_s`. Las sesiones todavía en curso
        (closed_at is None) nunca se tocan aquí, sin importar su edad.

        Returns:
            revision_id de cada sesión liberada en esta pasada.
        """
        now = self._clock()
        expired = [
            revision_id
            for revision_id, session in self._sessions.items()
            if session.closed_at is not None and (now - session.closed_at) >= ttl_s
        ]
        for revision_id in expired:
            self._sessions.pop(revision_id, None)
        return expired

    async def sweep_forever(self, ttl_s: float, interval_s: float) -> None:
        """Barrido periódico (DEF-16): corre sweep_expired cada
        `interval_s` hasta que la tarea se cancela (ver fog/main.py)."""
        while True:
            await asyncio.sleep(interval_s)
            self.sweep_expired(ttl_s)
