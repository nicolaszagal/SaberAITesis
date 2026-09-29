"""ObtenerCombate — consulta de solo lectura del combate configurado (F-039).

Permite al frontend validar el combate activo que recuerda entre recargas.
No modifica nada.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fog.domain.errors import RecursoNoEncontrado
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort


@dataclass(frozen=True)
class DetalleCombate:
    """Combate con el árbitro y los alias de sus tiradores. El brazo armado
    usa el dominio del esquema (`diestro` | `zurdo`)."""

    id: uuid.UUID
    pista: str
    arbitro_id: uuid.UUID
    arbitro: str
    alias_a: str
    brazo_a: str
    alias_b: str
    brazo_b: str


class ObtenerCombate:
    def __init__(self, uow: UnidadDeTrabajoPort):
        self._uow = uow

    async def execute(self, combate_id: uuid.UUID) -> DetalleCombate:
        """Lee un combate con su árbitro y sus tiradores.

        Args:
            combate_id: id del combate (el `match_id` de la API).

        Returns:
            El combate con pista, árbitro, alias y brazo armado de A y B.

        Raises:
            RecursoNoEncontrado: si el combate no existe.
        """
        async with self._uow.transaccion() as tx:
            combate = await tx.combates.obtener(combate_id)
            if combate is None:
                raise RecursoNoEncontrado(f"combate {combate_id}")
            arbitro = await tx.usuarios.obtener(combate.arbitro_id)
            tirador_a = await tx.tiradores.obtener(combate.tirador_a_id)
            tirador_b = await tx.tiradores.obtener(combate.tirador_b_id)
            if arbitro is None or tirador_a is None or tirador_b is None:
                # Las claves foráneas del esquema lo impiden; se falla explícito
                # en vez de devolver un combate incompleto.
                raise RecursoNoEncontrado(f"datos del combate {combate_id}")
            return DetalleCombate(
                id=combate.id,
                pista=combate.pista,
                arbitro_id=arbitro.id,
                arbitro=arbitro.nombre,
                alias_a=tirador_a.alias,
                brazo_a=combate.brazo_a,
                alias_b=tirador_b.alias,
                brazo_b=combate.brazo_b,
            )
