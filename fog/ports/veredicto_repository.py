"""VeredictoRepositoryPort — persistencia de `sabre.veredicto` (CU-10).
Sin update ni delete: `tg_veredicto_inmutable` los bloquea igual (RNF-05).

`obtener_por_revision` es lo que usa D03 para devolver 409 si la revisión
ya tiene un veredicto registrado (`revision_id` es UNIQUE en el esquema).
"""

import uuid
from abc import ABC, abstractmethod

from fog.domain.audit_models import Veredicto


class VeredictoRepositoryPort(ABC):
    @abstractmethod
    async def crear(
        self,
        *,
        revision_id: uuid.UUID,
        decision: str,
        arbitro_id: uuid.UUID,
        clase_final: str | None = None,
    ) -> Veredicto:
        """Inserta el veredicto.

        Raises:
            VeredictoYaRegistrado: si la revisión ya tiene uno.
        """
        raise NotImplementedError

    @abstractmethod
    async def obtener_por_revision(self, revision_id: uuid.UUID) -> Veredicto | None:
        raise NotImplementedError
