"""EventoRepositoryPort — persistencia de `sabre.evento`.

Métodos mínimos: validar/leer un evento existente al configurar un combate
(D03, CU-01), listar los eventos para la pantalla de configuración y buscar
por nombre para la sesión de validación (scripts/crear_sesion_validacion.py).
Sin update/delete: no hay caso de uso documentado que los requiera.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import date

from fog.domain.audit_models import Evento


class EventoRepositoryPort(ABC):
    @abstractmethod
    async def crear(
        self, *, nombre: str, fecha: date, tipo: str, lugar: str | None = None
    ) -> Evento:
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, evento_id: uuid.UUID) -> Evento | None:
        raise NotImplementedError

    @abstractmethod
    async def obtener_por_nombre(self, nombre: str) -> Evento | None:
        """Evento con ese nombre exacto.

        Returns:
            El evento, o None si no existe. Si hubiera varios con el mismo
            nombre (el esquema no lo impide), el más antiguo por fecha.
        """
        raise NotImplementedError

    @abstractmethod
    async def listar(self) -> list[Evento]:
        """Todos los eventos, del más reciente al más antiguo (por fecha y
        luego por nombre)."""
        raise NotImplementedError
