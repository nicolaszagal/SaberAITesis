"""TocadoRepositoryPort — persistencia de `sabre.tocado` y `sabre.tocado_clip`
(CU-02, CU-03, CU-04).
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from fog.domain.audit_models import Tocado


class TocadoRepositoryPort(ABC):
    @abstractmethod
    async def crear(
        self,
        *,
        combate_id: uuid.UUID,
        fuente: str,
        luz_a: bool,
        luz_b: bool,
        t_tocado_utc: datetime | None = None,
        t_tocado_ms: int | None = None,
        registrado_por: uuid.UUID | None = None,
    ) -> Tocado:
        raise NotImplementedError

    @abstractmethod
    async def vincular_clip(
        self, tocado_id: uuid.UUID, clip_id: uuid.UUID, frame_tocado: int
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, tocado_id: uuid.UUID) -> Tocado | None:
        raise NotImplementedError
