"""RegistrarVeredicto — CU-10 y CU-11 (RF-20, RF-21, RF-22, RNF-01).

En una sola transacción: inserta `veredicto`, cierra `revision_var` e
inserta `registro_auditoria` con el snapshot. Si cualquier paso falla no
queda nada: sin veredicto la revisión no se cierra. El sistema solo
sugiere; el punto lo decide el árbitro (este caso de uso no asigna puntos).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fog.domain.audit_models import Auditoria, Revision, Veredicto
from fog.domain.errors import (
    ClasificacionPendiente,
    RecursoNoEncontrado,
    VeredictoInvalido,
    VeredictoYaRegistrado,
)
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

CLASES = (
    "AtaqueA", "AtaqueB", "ContraataqueA", "ContraataqueB", "RiposteA", "RiposteB",
)
DECISIONES = ("mantener", "cambiar", "anular")


@dataclass(frozen=True)
class VeredictoRegistrado:
    combate_id: uuid.UUID
    veredicto: Veredicto
    revision: Revision
    auditoria: Auditoria


def _a_json(valor: Any) -> Any:
    """Convierte dataclasses, UUID, fechas y Decimal a tipos JSON."""
    if is_dataclass(valor) and not isinstance(valor, type):
        return _a_json(asdict(valor))
    if isinstance(valor, dict):
        return {k: _a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_a_json(v) for v in valor]
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def construir_snapshot(*, revision, tocado, clasificacion, veredicto, modelo) -> dict:
    """Arma el snapshot JSON del registro de auditoría (CU-11).

    Args:
        revision: revisión ya cerrada.
        tocado: tocado revisado.
        clasificacion: sugerencia registrada (disponible o no).
        veredicto: decisión del árbitro.
        modelo: versión de modelo que produjo la clasificación.

    Returns:
        Diccionario serializable con revisión, tocado, clasificación,
        veredicto, modelo y reglamento.
    """
    return _a_json(
        {
            "revision": revision,
            "tocado": tocado,
            "clasificacion": clasificacion,
            "veredicto": veredicto,
            "modelo": modelo,
            "reglamento": modelo.reglamento,
        }
    )


class RegistrarVeredicto:
    def __init__(self, uow: UnidadDeTrabajoPort):
        self._uow = uow

    async def execute(
        self,
        *,
        revision_id: uuid.UUID,
        decision: str,
        clase_final: str | None,
        arbitro_id: uuid.UUID,
    ) -> VeredictoRegistrado:
        """Registra el veredicto de una revisión y la cierra con su registro
        de auditoría.

        Args:
            revision_id: revisión que se decide (un combate admite N).
            decision: `mantener`, `cambiar` o `anular`.
            clase_final: obligatoria con `cambiar`; prohibida con `anular`.
            arbitro_id: usuario que decide.

        Returns:
            Veredicto, revisión cerrada y registro de auditoría.

        Raises:
            VeredictoInvalido: `cambiar` sin clase_final, `anular` con
                clase_final, o valores fuera de los dominios del esquema.
            RecursoNoEncontrado: árbitro o revisión inexistentes.
            VeredictoYaRegistrado: la revisión ya tiene veredicto (409).
            ClasificacionPendiente: la revisión no tiene clasificación.
        """
        if decision not in DECISIONES:
            raise VeredictoInvalido(f"decision desconocida: {decision!r}")
        if decision == "cambiar" and clase_final is None:
            raise VeredictoInvalido("decision='cambiar' requiere clase_final")
        if decision == "anular" and clase_final is not None:
            raise VeredictoInvalido("decision='anular' no admite clase_final")
        if clase_final is not None and clase_final not in CLASES:
            raise VeredictoInvalido(f"clase_final desconocida: {clase_final!r}")

        async with self._uow.transaccion() as tx:
            if await tx.usuarios.obtener(arbitro_id) is None:
                raise RecursoNoEncontrado(f"usuario (árbitro) {arbitro_id}")
            revision = await tx.revisiones.obtener(revision_id)
            if revision is None:
                raise RecursoNoEncontrado(f"revisión {revision_id}")
            if await tx.veredictos.obtener_por_revision(revision.id) is not None:
                raise VeredictoYaRegistrado(str(revision.id))
            if revision.clasificacion_id is None:
                raise ClasificacionPendiente(str(revision.id))

            tocado = await tx.tocados.obtener(revision.tocado_id)
            clasificacion = await tx.clasificaciones.obtener(revision.clasificacion_id)
            modelo = await tx.modelos.obtener(clasificacion.modelo_version_id)

            veredicto = await tx.veredictos.crear(
                revision_id=revision.id,
                decision=decision,
                clase_final=clase_final,
                arbitro_id=arbitro_id,
            )
            await tx.revisiones.cerrar(revision.id, veredicto.registrado_en)
            cerrada = replace(revision, cerrada_en=veredicto.registrado_en)
            auditoria = await tx.auditoria.registrar(
                revision_id=revision.id,
                snapshot=construir_snapshot(
                    revision=cerrada,
                    tocado=tocado,
                    clasificacion=clasificacion,
                    veredicto=veredicto,
                    modelo=modelo,
                ),
            )
        return VeredictoRegistrado(
            combate_id=tocado.combate_id,
            veredicto=veredicto,
            revision=cerrada,
            auditoria=auditoria,
        )
