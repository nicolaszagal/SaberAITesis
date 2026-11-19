"""Tests de SessionRegistry/MatchSession: cierre de RTCPeerConnection y
liberación de sesiones pasado SESSION_TTL_S (DEF-16 — antes
`SessionRegistry.remove` nunca se invocaba, así que las sesiones y su
RTCPeerConnection se acumulaban para siempre).

Usa un reloj falso (FakeClock) inyectado en SessionRegistry/MatchSession
en vez de esperar tiempo real, igual que el pedido del prompt."""

from __future__ import annotations

import asyncio

from fog.domain.models import MotivoNoDisponible, UnavailableResult, VerdictView, WeaponSide
from fog.infrastructure.sesiones.session_registry import SessionRegistry


class FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _verdict(revision_id: str) -> VerdictView:
    return VerdictView(
        match_id="m", revision_id=revision_id, fencer="ROJ", action="AttackA", confidence=0.9
    )


def _unavailable(revision_id: str) -> UnavailableResult:
    return UnavailableResult(
        match_id="m", revision_id=revision_id, motivo=MotivoNoDisponible.POSE_INCOMPLETA
    )


async def test_set_verdict_marks_closed_at():
    """Entregar el veredicto cierra la sesión en el instante del reloj."""
    clock = FakeClock(t=10.0)
    sessions = SessionRegistry(clock=clock)
    session = sessions.create("m", "m3", WeaponSide.RIGHT, WeaponSide.RIGHT)

    await session.set_verdict(_verdict("m3"))

    assert session.closed_at == 10.0


async def test_sweep_expired_removes_sessions_past_ttl():
    clock = FakeClock(t=0.0)
    sessions = SessionRegistry(clock=clock)
    session = sessions.create("m", "old", WeaponSide.RIGHT, WeaponSide.RIGHT)
    await session.set_verdict(_verdict("old"))

    clock.advance(120.0)  # == SESSION_TTL_S por defecto

    removed = sessions.sweep_expired(ttl_s=120.0)

    assert removed == ["old"]
    assert sessions.get("old") is None


async def test_sweep_expired_keeps_sessions_within_ttl():
    clock = FakeClock(t=0.0)
    sessions = SessionRegistry(clock=clock)
    session = sessions.create("m", "recent", WeaponSide.RIGHT, WeaponSide.RIGHT)
    await session.set_verdict(_verdict("recent"))

    clock.advance(119.0)  # todavía dentro de la ventana de conexión tardía

    removed = sessions.sweep_expired(ttl_s=120.0)

    assert removed == []
    assert sessions.get("recent") is not None


async def test_sweep_expired_never_removes_sessions_still_in_progress():
    """Una sesión sin veredicto ni "no disponible" (closed_at is None)
    nunca se libera, sin importar cuánto tiempo pasó: liberarla cortaría
    una revisión en curso."""
    clock = FakeClock(t=0.0)
    sessions = SessionRegistry(clock=clock)
    sessions.create("m", "in-progress", WeaponSide.RIGHT, WeaponSide.RIGHT)

    clock.advance(10_000.0)

    removed = sessions.sweep_expired(ttl_s=120.0)

    assert removed == []
    assert sessions.get("in-progress") is not None


async def test_sweep_forever_runs_sweep_periodically():
    clock = FakeClock(t=0.0)
    sessions = SessionRegistry(clock=clock)
    session = sessions.create("m", "m-loop", WeaponSide.RIGHT, WeaponSide.RIGHT)
    await session.set_verdict(_verdict("m-loop"))
    clock.advance(999.0)  # ya pasó el TTL antes de que arranque el barrido

    task = asyncio.create_task(sessions.sweep_forever(ttl_s=120.0, interval_s=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert sessions.get("m-loop") is None


def test_create_indexa_por_revision_y_permite_varias_del_mismo_combate():
    sessions = SessionRegistry()

    primera = sessions.create("combate", "rev-1", WeaponSide.RIGHT, WeaponSide.LEFT)
    segunda = sessions.create("combate", "rev-2", WeaponSide.RIGHT, WeaponSide.LEFT)

    assert sessions.get("rev-1") is primera
    assert sessions.get("rev-2") is segunda
    assert (primera.match_id, primera.revision_id) == ("combate", "rev-1")
    assert sessions.get("combate") is None  # el combate ya no es clave de sesión
