"""ConfigurarCombate — CU-01 (F-039, RF-07): crea el combate con sus dos
tiradores en una sola transacción.

`configurado_por` es el propio árbitro: no hay login ni operador
identificado en la interfaz (decisión del autor, prompt D03).

Los tiradores se guardan con `es_menor = true`, `consentimiento_firmado =
false`, y `consentimiento_fecha` y `firmante` nulos (valor conservador, V01b):
en V1 los consentimientos se gestionan en papel fuera del sistema y el sistema
no registra uno que no existe.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fog.domain.audit_models import Combate
from fog.domain.errors import RecursoNoEncontrado
from fog.domain.models import WeaponSide, brazo_de
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort


@dataclass(frozen=True)
class DatosTirador:
    """Datos del tirador que captura la configuración del combate.

    `alias` vacío o en blanco se sustituye por "Tirador A" / "Tirador B".
    """

    alias: str | None
    weapon_side: WeaponSide


class ConfigurarCombate:
    def __init__(self, uow: UnidadDeTrabajoPort):
        self._uow = uow

    async def execute(
        self,
        *,
        evento_id: uuid.UUID,
        pista: str,
        tirador_a: DatosTirador,
        tirador_b: DatosTirador,
        arbitro_id: uuid.UUID,
    ) -> Combate:
        """Crea tiradores y combate.

        Args:
            evento_id: evento existente al que pertenece el combate.
            pista: pista asignada.
            tirador_a: datos del tirador A (alias opcional y brazo armado).
            tirador_b: datos del tirador B.
            arbitro_id: usuario árbitro; también queda como `configurado_por`.

        Returns:
            El combate creado; su `id` es el `match_id` de la API.

        Raises:
            RecursoNoEncontrado: si el evento o el árbitro no existen.
        """
        async with self._uow.transaccion() as tx:
            if await tx.eventos.obtener(evento_id) is None:
                raise RecursoNoEncontrado(f"evento {evento_id}")
            if await tx.usuarios.obtener(arbitro_id) is None:
                raise RecursoNoEncontrado(f"usuario (árbitro) {arbitro_id}")

            filas = []
            for lado, datos in (("A", tirador_a), ("B", tirador_b)):
                filas.append(
                    await tx.tiradores.crear(
                        alias=(datos.alias or "").strip() or f"Tirador {lado}",
                        brazo_habitual=brazo_de(datos.weapon_side),
                        es_menor=True,
                        consentimiento_firmado=False,
                        consentimiento_fecha=None,
                        firmante=None,
                    )
                )
            return await tx.combates.crear(
                evento_id=evento_id,
                pista=pista,
                tirador_a_id=filas[0].id,
                tirador_b_id=filas[1].id,
                brazo_a=brazo_de(tirador_a.weapon_side),
                brazo_b=brazo_de(tirador_b.weapon_side),
                arbitro_id=arbitro_id,
                configurado_por=arbitro_id,
            )
