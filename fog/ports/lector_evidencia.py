"""LectorEvidenciaPort — lectura del log de evidencia de L01
(EVIDENCE_DIR/<evento_id>.jsonl) para conciliarlo con la base (L02).
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LecturaEvidencia:
    """Revisiones registradas en el JSONL de un evento."""

    presente: bool
    revision_ids: list[str]
    lineas_ilegibles: int


class LectorEvidenciaPort(ABC):
    @abstractmethod
    def leer(self, evento_id: uuid.UUID) -> LecturaEvidencia:
        """Lee el JSONL del evento sin modificarlo.

        Args:
            evento_id: id del evento.

        Returns:
            Los `revision_id` de cada línea legible, en orden de archivo.
            Si el archivo no existe, `presente` es False y no hay ids.
        """
        raise NotImplementedError
