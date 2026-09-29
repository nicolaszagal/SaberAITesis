"""ConsultaEvidenciaRepositoryPort — lectura de las revisiones con veredicto
de un evento, para el resumen de validación (L02). Solo lectura.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from fog.domain.audit_models import (
    Auditoria,
    Clasificacion,
    ModeloVersion,
    Revision,
    Tocado,
    Veredicto,
)


@dataclass(frozen=True)
class RevisionConVeredicto:
    """Lo registrado de una revisión con veredicto; son las entradas de
    `construir_linea`. Las clases van con los nombres del modelo."""

    revision: Revision
    tocado: Tocado
    clasificacion: Clasificacion
    veredicto: Veredicto
    modelo: ModeloVersion
    auditoria: Auditoria


class ConsultaEvidenciaRepositoryPort(ABC):
    @abstractmethod
    async def existe_evento(self, evento_id: uuid.UUID) -> bool:
        """Indica si el evento existe.

        Args:
            evento_id: id de `evento`.

        Returns:
            True si hay un evento con ese id.
        """
        raise NotImplementedError

    @abstractmethod
    async def listar_con_veredicto(
        self, evento_id: uuid.UUID
    ) -> list[RevisionConVeredicto]:
        """Lista las revisiones con veredicto de los combates de un evento.

        Args:
            evento_id: id de `evento`.

        Returns:
            Revisiones ordenadas por `veredicto.registrado_en` y luego por
            id de revisión (orden estable entre ejecuciones).
        """
        raise NotImplementedError
