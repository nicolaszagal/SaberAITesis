"""CombateActivoPort — el combate activo del nodo (EDGE02, uno por nodo).

Al configurar un combate, Fog lo marca como activo; Edge sube los tocados a ese. Cerrar la sesión
lo limpia. Es una decisión explícita: no se deduce de "el último configurado".
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod


class CombateActivoPort(ABC):
    @abstractmethod
    def establecer(self, combate_id: uuid.UUID) -> None:
        """Marca `combate_id` como el combate activo (reemplaza al anterior)."""
        raise NotImplementedError

    @abstractmethod
    def obtener(self) -> uuid.UUID | None:
        """El combate activo, o `None` si no hay (o si se cerró la sesión)."""
        raise NotImplementedError

    @abstractmethod
    def limpiar(self) -> None:
        """Deja el nodo sin combate activo."""
        raise NotImplementedError
