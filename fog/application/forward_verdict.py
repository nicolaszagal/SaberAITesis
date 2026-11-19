"""ForwardVerdictToClient — caso de uso: espera el veredicto de Cloud
(VerdictStreamSubscriberPort) y lo guarda en la sesión de la revisión.
Mirror de `_wait_for_verdict` del fog/main.py anterior, ahora desacoplado
de redis.asyncio directo.

SEC02: solo se acepta un resultado esperado. Se descarta (con aviso en el log
técnico, sin tocar la base) el de una revisión sin sesión pendiente y el
veredicto de un modelo distinto del activo.
"""

from __future__ import annotations

import logging

from fog.domain.models import UnavailableResult, VerdictView
from fog.infrastructure.sesiones.session_registry import SessionRegistry
from fog.ports.modelo_version_repository import ModeloVersionRepositoryPort
from fog.ports.verdict_subscriber import VerdictStreamSubscriberPort

log = logging.getLogger("fog.application")


def _run_y_archivo(ruta: str | None) -> tuple[str, ...] | None:
    """Los dos últimos segmentos de una ruta (`<run_id>/<archivo>`).

    Cloud publica el modelo como `lstm_6class/<run_id>/best_model.pt` y Fog guarda
    la ruta del checkpoint como `.../checkpoints/<run_id>/best_model.pt`: ambas
    salen del mismo directorio de corrida, y solo coinciden en este sufijo.

    Args:
        ruta: ruta del checkpoint o nombre de modelo publicado por Cloud.

    Returns:
        Los dos últimos segmentos, o None si la ruta no los tiene.
    """
    if not ruta:
        return None
    partes = [p for p in ruta.replace("\\", "/").split("/") if p]
    return tuple(partes[-2:]) if len(partes) >= 2 else None


class ForwardVerdictToClient:
    def __init__(
        self,
        subscriber: VerdictStreamSubscriberPort,
        sessions: SessionRegistry,
        modelos: ModeloVersionRepositoryPort,
    ):
        self._subscriber = subscriber
        self._sessions = sessions
        self._modelos = modelos

    async def _aceptar(self, revision_id: str, resultado: VerdictView | UnavailableResult) -> bool:
        """Decide si un resultado leído del stream de la revisión vale.

        Args:
            revision_id: revisión del stream.
            resultado: veredicto o "no disponible" leído.

        Returns:
            True si hay sesión pendiente y, para un veredicto, el modelo es el activo.
        """
        sesion = self._sessions.get(revision_id)
        if sesion is None or sesion.closed_at is not None:
            log.warning("[%s] resultado descartado: no hay sesión pendiente", revision_id)
            return False
        if isinstance(resultado, UnavailableResult):
            return True
        activo = await self._modelos.obtener_activo()
        esperado = _run_y_archivo(activo.checkpoint_uri) if activo is not None else None
        if esperado is None or _run_y_archivo(resultado.modelo) != esperado:
            log.warning(
                "[%s] veredicto descartado: modelo %r distinto del activo (%s)",
                revision_id, resultado.modelo, activo.nombre if activo else "ninguno",
            )
            return False
        return True

    async def execute(self, revision_id: str) -> None:
        """Espera el resultado de Cloud para la revisión y lo entrega a su sesión.

        Args:
            revision_id: revisión cuyo veredicto se espera.
        """
        sesion = self._sessions.get(revision_id)
        if sesion is None or sesion.closed_at is not None:
            log.warning("[%s] no se espera veredicto: no hay sesión pendiente", revision_id)
            return

        resultado = await self._subscriber.wait_for_verdict(
            revision_id, aceptar=lambda r: self._aceptar(revision_id, r)
        )

        session = self._sessions.get(revision_id)
        if session is None:
            log.warning("[%s] veredicto recibido pero la sesión ya no existe", revision_id)
            return

        if isinstance(resultado, UnavailableResult):
            await session.set_unavailable(resultado)
        else:
            await session.set_verdict(resultado)
