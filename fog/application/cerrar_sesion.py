"""CerrarSesion — cierre de la sesión de validación (EDGE02, D-22).

Orden, y la razón de cada paso:
    1. respaldo verificado (sin clips) del evento del combate activo;
    2. SOLO si el respaldo pasó: borrar los clips de la sesión (Fog y Edge) y limpiar el combate activo.

Si el respaldo falla no se borra nada ni se cambia el combate activo: el operador puede reintentar.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from fog.application.purgar_clips import PurgarClips
from fog.domain.errors import ErrorDeDominio
from fog.ports.combate_activo import CombateActivoPort
from fog.ports.respaldo_sesion import RespaldoSesionPort
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

log = logging.getLogger("fog.application")


class SinCombateActivo(ErrorDeDominio):
    """No hay combate activo: no hay sesión que cerrar."""


class RespaldoFallido(ErrorDeDominio):
    """El respaldo o su verificación fallaron; no se borró nada. El texto trae el detalle."""


@dataclass(frozen=True)
class SesionCerrada:
    """Qué hizo el cierre.

    Attributes:
        respaldo: salida del respaldo verificado.
        clips_borrados: archivos de clip de Fog borrados.
        archivos_edge_borrados: archivos de clip y JSON de Edge borrados.
    """

    respaldo: str
    clips_borrados: int
    archivos_edge_borrados: int


class CerrarSesion:
    def __init__(
        self,
        uow: UnidadDeTrabajoPort,
        activo: CombateActivoPort,
        respaldo: RespaldoSesionPort,
        purgar: PurgarClips,
        edge_dir: str | Path,
    ):
        self._uow = uow
        self._activo = activo
        self._respaldo = respaldo
        self._purgar = purgar
        self._edge_dir = Path(edge_dir)
        self._lock = asyncio.Lock()

    async def execute(self) -> SesionCerrada:
        """Respalda, verifica y, solo si pasó, purga los clips de la sesión.

        Returns:
            El resumen del cierre.

        Raises:
            SinCombateActivo: si no hay combate activo.
            RespaldoFallido: si el respaldo no pasó (no se borró nada).
        """
        async with self._lock:  # un solo cierre a la vez
            combate_id = self._activo.obtener()
            if combate_id is None:
                raise SinCombateActivo("no hay un combate activo")
            async with self._uow.transaccion() as tx:
                combate = await tx.combates.obtener(combate_id)
            if combate is None or combate.evento_id is None:
                raise SinCombateActivo("el combate activo no existe o no tiene evento")
            resultado = await self._respaldo.respaldar(combate.evento_id)
            if not resultado.ok:
                log.error("cierre de sesión: el respaldo falló; no se borra nada. %s", resultado.detalle)
                raise RespaldoFallido(resultado.detalle)
            clips = await self._purgar.execute(evento_id=combate.evento_id)
            edge = await asyncio.to_thread(self._purgar_edge)
            self._activo.limpiar()
            log.info("sesión cerrada: %d clip(s) de Fog y %d archivo(s) de Edge borrados", clips, edge)
            return SesionCerrada(resultado.detalle, clips, edge)

    def _purgar_edge(self) -> int:
        archivos = (
            [p for p in self._edge_dir.glob("tocado_*") if p.suffix in (".mp4", ".json")]
            if self._edge_dir.exists() else []
        )
        for p in archivos:
            p.unlink(missing_ok=True)
        return len(archivos)
