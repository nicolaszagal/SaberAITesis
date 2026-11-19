"""RespaldoSesionPort — respaldo verificado de una sesión (EDGE02, cierre de sesión)."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ResultadoRespaldo:
    """Resultado de un respaldo verificado.

    Attributes:
        ok: True solo si el respaldo se hizo Y pasó la verificación.
        detalle: salida del respaldo (o el motivo del fallo), para informar al operador.
    """

    ok: bool
    detalle: str


class RespaldoSesionPort(ABC):
    @abstractmethod
    async def respaldar(self, evento_id: uuid.UUID) -> ResultadoRespaldo:
        """Respalda y verifica la sesión (evento). Nunca lanza por un fallo del respaldo: lo informa."""
        raise NotImplementedError
