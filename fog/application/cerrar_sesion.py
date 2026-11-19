"""CerrarSesion — cierre de la sesión de validación (D-22).

Orden, y la razón de cada paso:
    1. respaldo verificado (sin clips) del evento del combate indicado;
    2. SOLO si el respaldo pasó: borrar los clips de la sesión.

Si el respaldo falla no se borra nada: el operador puede reintentar.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from fog.application.purgar_clips import PurgarClips
from fog.domain.errors import ErrorDeDominio
from fog.ports.respaldo_sesion import RespaldoSesionPort
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

log = logging.getLogger("fog.application")


class CombateInexistente(ErrorDeDominio):
    """El combate no existe o no tiene evento: no hay sesión que cerrar."""


class RespaldoFallido(ErrorDeDominio):
    """El respaldo o su verificación fallaron; no se borró nada. El texto trae el detalle."""


@dataclass(frozen=True)
class SesionCerrada:
    """Qué hizo el cierre.

    Attributes:
        respaldo: salida del respaldo verificado.
        clips_borrados: archivos de clip borrados.
    """

    respaldo: str
    clips_borrados: int


class CerrarSesion:
    def __init__(self, uow: UnidadDeTrabajoPort, respaldo: RespaldoSesionPort, purgar: PurgarClips):
        self._uow = uow
        self._respaldo = respaldo
        self._purgar = purgar
        self._lock = asyncio.Lock()

    async def execute(self, combate_id: uuid.UUID) -> SesionCerrada:
        """Respalda, verifica y, solo si pasó, purga los clips de la sesión del combate.

        Args:
            combate_id: combate cuya sesión (evento) se cierra.

        Returns:
            El resumen del cierre.

        Raises:
            CombateInexistente: si el combate no existe o no tiene evento.
            RespaldoFallido: si el respaldo no pasó (no se borró nada).
        """
        async with self._lock:  # un solo cierre a la vez
            async with self._uow.transaccion() as tx:
                combate = await tx.combates.obtener(combate_id)
            if combate is None or combate.evento_id is None:
                raise CombateInexistente("el combate no existe o no tiene evento")
            resultado = await self._respaldo.respaldar(combate.evento_id)
            if not resultado.ok:
                log.error("cierre de sesión: el respaldo falló; no se borra nada. %s", resultado.detalle)
                raise RespaldoFallido(resultado.detalle)
            clips = await self._purgar.execute(combate.evento_id)
            log.info("sesión cerrada: %d clip(s) borrados", clips)
            return SesionCerrada(resultado.detalle, clips)
