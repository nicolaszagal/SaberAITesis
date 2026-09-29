"""UsuarioRepositoryPort — `sabre.usuario` (árbitro y operador de un combate).
La API solo lee (no hay login, RF-26 es COULD); las filas se siembran fuera
de ella con scripts/crear_sesion_validacion.py, que es quien usa `crear`.
"""

import uuid
from abc import ABC, abstractmethod

from fog.domain.audit_models import Usuario


class UsuarioRepositoryPort(ABC):
    @abstractmethod
    async def obtener(self, usuario_id: uuid.UUID) -> Usuario | None:
        raise NotImplementedError

    @abstractmethod
    async def crear(self, *, nombre: str, rol: str) -> Usuario:
        """Inserta un usuario activo.

        Args:
            nombre: nombre visible.
            rol: `arbitro`, `operador` o `administrador` (dominio del esquema).
        """
        raise NotImplementedError

    @abstractmethod
    async def obtener_por_nombre_y_rol(self, nombre: str, rol: str) -> Usuario | None:
        """Usuario con ese nombre exacto y rol.

        Returns:
            El usuario, o None. Si hubiera varios, el más antiguo.
        """
        raise NotImplementedError

    @abstractmethod
    async def listar(self, rol: str | None = None) -> list[Usuario]:
        """Usuarios ordenados por nombre.

        Args:
            rol: si se indica, solo los de ese rol.
        """
        raise NotImplementedError
