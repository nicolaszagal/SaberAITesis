"""AuditoriaRepositoryPort — persistencia de `sabre.registro_auditoria`
(CU-11, RNF-05). Solo adición: sin update ni delete (`tg_auditoria_inmutable`
los bloquea igual), y sin siquiera un método de lectura — CU-12 (consultar
auditoría) no está en el alcance de D02/D03.

El hash y el encadenamiento con el registro anterior los calcula el
trigger `tg_auditoria_hash` en la base; este puerto solo entrega el
snapshot.
"""

import uuid
from abc import ABC, abstractmethod

from fog.domain.audit_models import Auditoria


class AuditoriaRepositoryPort(ABC):
    @abstractmethod
    async def registrar(self, *, revision_id: uuid.UUID, snapshot: dict) -> Auditoria:
        raise NotImplementedError
