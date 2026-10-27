"""RazonamientoRepositoryPort — persistencia de `sabre.evidencia` (CU-09,
F-035, D-16): los eventos y el criterio FIE de cada clasificación.

Sin update ni delete: el razonamiento se escribe una vez, junto con la
clasificación, y no se recalcula (D-17).
"""

import uuid
from abc import ABC, abstractmethod

from fog.domain.razonamiento import FilaEvidencia


class RazonamientoRepositoryPort(ABC):
    @abstractmethod
    async def registrar(
        self, clasificacion_id: uuid.UUID, filas: list[FilaEvidencia]
    ) -> None:
        """Inserta las filas de evidencia de una clasificación.

        Args:
            clasificacion_id: clasificación a la que pertenecen.
            filas: filas a insertar.
        """
        raise NotImplementedError

    @abstractmethod
    async def listar(self, clasificacion_id: uuid.UUID) -> list[FilaEvidencia]:
        """Devuelve las filas de evidencia de una clasificación.

        Args:
            clasificacion_id: clasificación consultada.

        Returns:
            Las filas en el orden en que se escribieron; vacía si no hay
            (revisión anterior a EXP03 o clasificación no disponible).
        """
        raise NotImplementedError
