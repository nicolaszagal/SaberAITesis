"""SessionRegistry — estado de runtime por match_id (RTCPeerConnection,
websocket del front, señal de luz, evento de veredicto). No es el
dominio: `Match` (fog/domain/models.py) es la entidad persistible; esto es
infraestructura de sesión en memoria del proceso de Fog mientras dura el
clip, equivalente al dict global `MATCHES` del fog/main.py anterior pero
encapsulado para que composition.py controle su ciclo de vida.

Ya no buffer-ea los frames recibidos (antes `self.frames: list[np.ndarray]`)
— track_consumer.py los procesa frame a frame contra un
PoseTrackingSession propio en cuanto llegan, en vez de acumularlos aquí
para procesarlos todos juntos al final del clip.
"""

from __future__ import annotations

import asyncio

from aiortc import RTCPeerConnection

from fog.domain.models import LuzSignal, VerdictView, WeaponSide


class MatchSession:
    def __init__(self, match_id: str, weapon_side_a: WeaponSide, weapon_side_b: WeaponSide):
        self.match_id = match_id
        self.weapon_side_a = weapon_side_a
        self.weapon_side_b = weapon_side_b
        self.pc: RTCPeerConnection | None = None
        self.ws = None  # fastapi.WebSocket, asignado por GET /ws/veredicto/{match_id}
        self.luz: LuzSignal | None = None
        self.luz_event = asyncio.Event()
        self.verdict: VerdictView | None = None
        self.verdict_event = asyncio.Event()

    def set_luz(self, luz: LuzSignal) -> None:
        self.luz = luz
        self.luz_event.set()

    def set_verdict(self, verdict: VerdictView) -> None:
        self.verdict = verdict
        self.verdict_event.set()


class SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, MatchSession] = {}

    def create(self, match_id: str, weapon_side_a: WeaponSide, weapon_side_b: WeaponSide) -> MatchSession:
        session = MatchSession(match_id, weapon_side_a, weapon_side_b)
        self._sessions[match_id] = session
        return session

    def get(self, match_id: str) -> MatchSession | None:
        return self._sessions.get(match_id)

    def remove(self, match_id: str) -> None:
        self._sessions.pop(match_id, None)
