"""UsuarioRepositoryPort — lectura de `sabre.usuario` (árbitro y operador de
un combate). Las filas se siembran fuera de la API (no hay login, RF-26 es
COULD), así que el puerto solo consulta.
"""

import uuid
from abc import ABC, abstractmethod

from fog.domain.audit_models import Usuario


class UsuarioRepositoryPort(ABC):
    @abstractmethod
    async def obtener(self, usuario_id: uuid.UUID) -> Usuario | None:
        raise NotImplementedError
