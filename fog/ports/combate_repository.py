"""CombateRepositoryPort — persistencia de `sabre.combate` (CU-01).

`crear` toma los IDs ya resueltos de tirador_a/b y árbitro (no de Tirador
ni Usuario: D02 no define esos puertos — D03 decide, al implementar
POST /matches/config, de dónde salen esos IDs a partir del alias que
ingresa la interfaz).
"""

import uuid
from abc import ABC, abstractmethod

from fog.domain.audit_models import Combate


class CombateRepositoryPort(ABC):
    @abstractmethod
    async def crear(
        self,
        *,
        pista: str,
        tirador_a_id: uuid.UUID,
        tirador_b_id: uuid.UUID,
        brazo_a: str,
        brazo_b: str,
        arbitro_id: uuid.UUID,
        configurado_por: uuid.UUID,
        evento_id: uuid.UUID | None = None,
        fase: str | None = None,
    ) -> Combate:
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, combate_id: uuid.UUID) -> Combate | None:
        raise NotImplementedError
