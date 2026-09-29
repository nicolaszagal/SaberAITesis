"""ConsultaRevisionRepositoryPort — lecturas de revisiones para la
interfaz (CU-07, CU-12). Solo lectura: no modifica nada.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from fog.domain.audit_models import DetalleRevision, ResumenRevision


class ConsultaRevisionRepositoryPort(ABC):
    @abstractmethod
    async def listar(
        self,
        *,
        evento_id: uuid.UUID | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[ResumenRevision]:
        """Lista las revisiones, de la más reciente a la más antigua.

        Args:
            evento_id: si se indica, solo las de combates de ese evento.
            desde: si se indica, solo las abiertas en o después de este
                instante (con zona horaria).
            hasta: si se indica, solo las abiertas en o antes de este
                instante (con zona horaria).

        Returns:
            Resúmenes ordenados por `abierta_en` descendente.
        """
        raise NotImplementedError

    @abstractmethod
    async def detalle(self, revision_id: uuid.UUID) -> DetalleRevision | None:
        """Devuelve una revisión con su sugerencia, veredicto y auditoría.

        Args:
            revision_id: id de `revision_var`.

        Returns:
            El detalle, o None si la revisión no existe.
        """
        raise NotImplementedError
