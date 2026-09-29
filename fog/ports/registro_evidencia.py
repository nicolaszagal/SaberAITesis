"""RegistroEvidenciaPort — log de evidencia de la validación (L01).

Separado del log técnico: solo recibe líneas de revisiones ya cerradas.
"""

from abc import ABC, abstractmethod

from fog.domain.evidencia import LineaEvidencia


class RegistroEvidenciaPort(ABC):
    @abstractmethod
    def registrar(self, linea: LineaEvidencia) -> None:
        """Registra la línea de una revisión cerrada.

        Args:
            linea: campos de evidencia de la revisión.

        Raises:
            OSError: si no se puede escribir el registro.
        """
        raise NotImplementedError
