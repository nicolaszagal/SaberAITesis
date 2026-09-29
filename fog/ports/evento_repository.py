"""EventoRepositoryPort — persistencia de `sabre.evento`.

Métodos mínimos que usa D03 (CU-01): validar/leer un evento existente al
configurar un combate. Sin CRUD completo (sin update/delete: no hay caso
de uso documentado que los requiera).
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
