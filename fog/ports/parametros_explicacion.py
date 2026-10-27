"""ParametrosExplicacionPort — carga de los parámetros U1 a U6 del
razonamiento (F-035). Separado del dominio: los valores viven en un archivo
versionado, no en el código.
"""

from abc import ABC, abstractmethod

from fog.domain.razonamiento import ParametrosExplicacion


class ParametrosExplicacionPort(ABC):
    @abstractmethod
    def cargar(self) -> ParametrosExplicacion:
        """Devuelve los parámetros vigentes.

        Returns:
            Los parámetros con su `version`.

        Raises:
            ValueError: si falta un parámetro o su valor no es válido.
        """
        raise NotImplementedError
