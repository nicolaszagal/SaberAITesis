"""TiradorRepositoryPort — persistencia de `sabre.tirador` (CU-01).

Cada configuración de combate crea sus dos tiradores: el alias no es único
en el esquema y no hay caso de uso documentado que reutilice tiradores.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import date

from fog.domain.audit_models import Tirador


class TiradorRepositoryPort(ABC):
    @abstractmethod
    async def crear(
        self,
        *,
        alias: str,
        brazo_habitual: str,
        es_menor: bool,
        consentimiento_firmado: bool = False,
        consentimiento_fecha: date | None = None,
        firmante: str | None = None,
    ) -> Tirador:
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, tirador_id: uuid.UUID) -> Tirador | None:
        raise NotImplementedError
