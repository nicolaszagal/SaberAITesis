"""Línea del log de evidencia (L01, T-017, protocolo_validacion.md).

Una línea por revisión cerrada. Solo los campos documentados: sin nombres de
atletas, sin frames, sin trazas. Se arma únicamente con lo ya registrado en
la base (revisión, tocado, clasificación, veredicto, modelo y auditoría).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fog.domain.audit_models import (
    Auditoria,
    Clasificacion,
    ModeloVersion,
    Revision,
    Tocado,
    Veredicto,
)

@dataclass(frozen=True)
class LineaEvidencia:
    """Campos exactos de una línea de evidencia (18), en orden de escritura.

    Las clases usan los nombres del modelo (`AttackA`, ..., `RiposteB`).
    """

    ts: str
    evento_id: str
    revision_id: str
    modelo: str
    luz_A: bool
    luz_B: bool
    disponible: bool
    motivo: str | None
    clase_sugerida: str | None
    confianza: float | None
    latencia_ms: int | None
    decision: str
    clase_final_arbitro: str | None
    concordancia: bool | None
    hash_auditoria: str
    latencia_inferencia_ms: int | None
    t_luz_a_ms: int | None
    t_luz_b_ms: int | None


def construir_linea(
    *,
    evento_id: UUID,
    revision: Revision,
    tocado: Tocado,
    clasificacion: Clasificacion,
    veredicto: Veredicto,
    modelo: ModeloVersion,
    auditoria: Auditoria,
) -> LineaEvidencia:
    """Arma la línea de evidencia de una revisión cerrada.

    Args:
        evento_id: evento del combate de la revisión.
        revision: revisión cerrada.
        tocado: tocado revisado (define las luces).
        clasificacion: sugerencia registrada, disponible o no.
        veredicto: decisión del árbitro.
        modelo: versión de modelo que produjo la clasificación.
        auditoria: registro de auditoría de la revisión.

    Returns:
        La línea con exactamente los campos documentados. `concordancia` es
        `clase_sugerida == clase_final_arbitro`, o None si la clasificación
        no estuvo disponible o el árbitro anuló.
    """
    concordancia = None
    if clasificacion.disponible and veredicto.clase_final is not None:
        concordancia = clasificacion.clase == veredicto.clase_final
    return LineaEvidencia(
        ts=_iso(veredicto.registrado_en),
        evento_id=str(evento_id),
        revision_id=str(revision.id),
        modelo=modelo.nombre,
        luz_A=tocado.luz_a,
        luz_B=tocado.luz_b,
        disponible=clasificacion.disponible,
        motivo=clasificacion.motivo_no_disp,
        clase_sugerida=clasificacion.clase,
        confianza=clasificacion.confianza,
        latencia_ms=clasificacion.latencia_ms,
        decision=veredicto.decision,
        clase_final_arbitro=veredicto.clase_final,
        concordancia=concordancia,
        hash_auditoria=auditoria.hash,
        latencia_inferencia_ms=clasificacion.latencia_inferencia_ms,
        t_luz_a_ms=tocado.t_luz_a_ms,
        t_luz_b_ms=tocado.t_luz_b_ms,
    )


def _iso(instante: datetime) -> str:
    return instante.isoformat()
