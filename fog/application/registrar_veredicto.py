"""RegistrarVeredicto — CU-10 y CU-11 (RF-20, RF-21, RF-22, RNF-01).

En una sola transacción: inserta `veredicto`, cierra `revision_var` e
inserta `registro_auditoria` con el snapshot. Si cualquier paso falla no
queda nada: sin veredicto la revisión no se cierra. El sistema solo
sugiere; el punto lo decide el árbitro (este caso de uso no asigna puntos).
"""

from __future__ import annotations

import logging
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
from fog.domain.evidencia import construir_linea
from fog.domain.models import CLASES_MODELO
from fog.ports.registro_evidencia import RegistroEvidenciaPort
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

log = logging.getLogger("fog.application")

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
        veredicto, modelo, reglamento y `vocabulario` (`"modelo"`: nombres
        de clase del modelo).
    """
    return _a_json(
        {
            "revision": revision,
            "tocado": tocado,
            "clasificacion": clasificacion,
            "veredicto": veredicto,
            "modelo": modelo,
            "reglamento": modelo.reglamento,
            # Las clases del snapshot usan los nombres del modelo, no los del esquema.
            "vocabulario": "modelo",
        }
    )


class RegistrarVeredicto:
    def __init__(
        self,
        uow: UnidadDeTrabajoPort,
        evidencia: RegistroEvidenciaPort | None = None,
    ):
        self._uow = uow
        self._evidencia = evidencia

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
            decision: `mantener`, `cambiar` o `anular`; describe la relación
                con la decisión original del árbitro en pista.
            clase_final: decisión final declarada. Obligatoria con `mantener`
                y `cambiar` (aunque la clasificación no estuviera
                disponible); prohibida con `anular`. Usa los nombres del
                modelo (`AttackA`, ...).
            arbitro_id: usuario que decide.

        Returns:
            Veredicto, revisión cerrada y registro de auditoría.

        Raises:
            VeredictoInvalido: `mantener` o `cambiar` sin clase_final,
                `anular` con clase_final, o valores fuera de los dominios.
            RecursoNoEncontrado: árbitro o revisión inexistentes.
            VeredictoYaRegistrado: la revisión ya tiene veredicto (409).
            ClasificacionPendiente: la revisión no tiene clasificación.
        """
        if decision not in DECISIONES:
            raise VeredictoInvalido(f"decision desconocida: {decision!r}")
        if decision in ("mantener", "cambiar") and clase_final is None:
            raise VeredictoInvalido(f"decision={decision!r} requiere clase_final")
        if decision == "anular" and clase_final is not None:
            raise VeredictoInvalido("decision='anular' no admite clase_final")
        if clase_final is not None and clase_final not in CLASES_MODELO:
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
            combate = await tx.combates.obtener(tocado.combate_id)

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
        log.info(
            "[%s] veredicto registrado: decision=%s clase_final=%s",
            revision.id, decision, clase_final,
        )
        self._registrar_evidencia(
            evento_id=combate.evento_id,
            revision=cerrada,
            tocado=tocado,
            clasificacion=clasificacion,
            veredicto=veredicto,
            modelo=modelo,
            auditoria=auditoria,
        )
        return VeredictoRegistrado(
            combate_id=tocado.combate_id,
            veredicto=veredicto,
            revision=cerrada,
            auditoria=auditoria,
        )

    def _registrar_evidencia(self, *, evento_id, **registrado) -> None:
        """Escribe la línea de evidencia con lo ya guardado en la base.

        Se llama después de confirmar la transacción. Si la escritura falla,
        el veredicto ya está registrado y auditado: solo se deja el error en
        el log técnico.
        """
        if self._evidencia is None or evento_id is None:
            return
        try:
            linea = construir_linea(evento_id=evento_id, **registrado)
            self._evidencia.registrar(linea)
        except Exception:
            log.exception(
                "[%s] no se pudo escribir el log de evidencia",
                registrado["revision"].id,
            )
