"""ListarEventos y ListarUsuarios — consultas de solo lectura para la
pantalla de configuración del combate (CU-01): qué evento y qué árbitro
elegir. No modifican nada.
"""

from __future__ import annotations

from fog.domain.audit_models import Evento, Usuario
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort


class ListarEventos:
    def __init__(self, uow: UnidadDeTrabajoPort):
        self._uow = uow

    async def execute(self) -> list[Evento]:
        """Lista los eventos.

        Returns:
            Eventos del más reciente al más antiguo (por fecha y nombre).
        """
        async with self._uow.transaccion() as tx:
            return await tx.eventos.listar()


class ListarUsuarios:
    def __init__(self, uow: UnidadDeTrabajoPort):
        self._uow = uow

    async def execute(self, rol: str | None = None) -> list[Usuario]:
        """Lista los usuarios.

        Args:
            rol: si se indica (`arbitro`, `operador` o `administrador`),
                solo los de ese rol.

        Returns:
            Usuarios ordenados por nombre.
        """
        async with self._uow.transaccion() as tx:
            return await tx.usuarios.listar(rol)
