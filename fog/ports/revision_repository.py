"""RevisionRepositoryPort — persistencia de `sabre.revision_var` (CU-05,
CU-07, CU-10). `cerrar` se usa recién cuando D03 registre el veredicto
(RF-21: sin veredicto la revisión no se cierra).
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from fog.domain.audit_models import Revision


class RevisionRepositoryPort(ABC):
    @abstractmethod
    async def crear(
        self, *, tocado_id: uuid.UUID, aceptada: bool, arbitro_id: uuid.UUID
    ) -> Revision:
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, revision_id: uuid.UUID) -> Revision | None:
        raise NotImplementedError

    @abstractmethod
    async def asignar_clasificacion(
        self, revision_id: uuid.UUID, clasificacion_id: uuid.UUID
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def cerrar(self, revision_id: uuid.UUID, cerrada_en: datetime) -> None:
        raise NotImplementedError
