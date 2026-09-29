"""ClipRepositoryPort — persistencia de `sabre.clip` (CU-02, CU-03).

Solo guarda URI y SHA-256 del archivo (FileStoragePort, D01, se encarga
del binario); esta tabla guarda los metadatos.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from fog.domain.audit_models import Clip


class ClipRepositoryPort(ABC):
    @abstractmethod
    async def crear(
        self,
        *,
        combate_id: uuid.UUID,
        origen: str,
        camara: str,
        uri: str,
        sha256: str,
        fps: float,
        ancho_px: int,
        alto_px: int,
        duracion_ms: int,
        t0_utc: datetime | None = None,
    ) -> Clip:
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, clip_id: uuid.UUID) -> Clip | None:
        raise NotImplementedError
