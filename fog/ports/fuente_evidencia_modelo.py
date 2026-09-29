"""FuenteEvidenciaModeloPort — tabla resumen de M01 (evidencia offline del
modelo de 6 clases). El resumen la copia tal cual: F1 no se recalcula en la
sesión (se mide offline sobre el test set, RNF-03).
"""

from abc import ABC, abstractmethod


class FuenteEvidenciaModeloPort(ABC):
    @abstractmethod
    def tabla_resumen_m01(self) -> str | None:
        """Devuelve la tabla resumen de M01 en Markdown.

        Returns:
            El texto de la sección, o None si la fuente no está disponible.
        """
        raise NotImplementedError
