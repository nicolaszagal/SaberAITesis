"""Adaptador SQLAlchemy de ConsultaRevisionRepositoryPort: lecturas con
JOIN sobre `revision_var`, `tocado`, `combate`, `clasificacion`,
`veredicto` y `registro_auditoria`. Traduce las clases del esquema al
vocabulario del modelo (ver `vocabulario.py`).
"""

import uuid
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import DetalleRevision, ResumenRevision
from fog.infrastructure.persistence.postgres.tables import (
    clasificacion as clasificacion_t,
)
from fog.infrastructure.persistence.postgres.tables import combate as combate_t
from fog.infrastructure.persistence.postgres.tables import (
    registro_auditoria as auditoria_t,
)
from fog.infrastructure.persistence.postgres.tables import revision_var as revision_t
from fog.infrastructure.persistence.postgres.tables import tocado as tocado_t
from fog.infrastructure.persistence.postgres.tables import veredicto as veredicto_t
from fog.infrastructure.persistence.postgres.vocabulario import (
    clase_a_modelo,
    probabilidades_a_modelo,
)
from fog.ports.consulta_revision_repository import ConsultaRevisionRepositoryPort

_UNION = (
    revision_t.join(tocado_t, tocado_t.c.id == revision_t.c.tocado_id)
    .join(combate_t, combate_t.c.id == tocado_t.c.combate_id)
    .outerjoin(clasificacion_t, clasificacion_t.c.id == revision_t.c.clasificacion_id)
    .outerjoin(veredicto_t, veredicto_t.c.revision_id == revision_t.c.id)
    .outerjoin(auditoria_t, auditoria_t.c.revision_id == revision_t.c.id)
)


def _confianza(fila: Row) -> float | None:
    return float(fila.confianza) if fila.confianza is not None else None


def _consulta_base() -> Select:
    return select(
        revision_t.c.id,
        combate_t.c.id.label("combate_id"),
        revision_t.c.abierta_en,
        revision_t.c.cerrada_en,
        clasificacion_t.c.disponible,
        clasificacion_t.c.motivo_no_disp,
        clasificacion_t.c.clase,
        clasificacion_t.c.tirador,
        clasificacion_t.c.confianza,
        clasificacion_t.c.probabilidades,
        veredicto_t.c.decision,
        veredicto_t.c.clase_final,
        veredicto_t.c.registrado_en,
        auditoria_t.c.seq.label("auditoria_seq"),
        auditoria_t.c.hash.label("auditoria_hash"),
    ).select_from(_UNION)


class PostgresConsultaRevisionRepository(ConsultaRevisionRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def listar(
        self,
        *,
        evento_id: uuid.UUID | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[ResumenRevision]:
        consulta = _consulta_base()
        if evento_id is not None:
            consulta = consulta.where(combate_t.c.evento_id == evento_id)
        if desde is not None:
            consulta = consulta.where(revision_t.c.abierta_en >= desde)
        if hasta is not None:
            consulta = consulta.where(revision_t.c.abierta_en <= hasta)
        consulta = consulta.order_by(revision_t.c.abierta_en.desc(), revision_t.c.id)
        async with self._session_factory() as session:
            filas = (await session.execute(consulta)).all()
        return [
            ResumenRevision(
                id=f.id,
                combate_id=f.combate_id,
                abierta_en=f.abierta_en,
                cerrada_en=f.cerrada_en,
                disponible=f.disponible,
                clase=clase_a_modelo(f.clase),
                confianza=_confianza(f),
                decision=f.decision,
                clase_final=clase_a_modelo(f.clase_final),
            )
            for f in filas
        ]

    async def detalle(self, revision_id: uuid.UUID) -> DetalleRevision | None:
        async with self._session_factory() as session:
            f = (
                await session.execute(_consulta_base().where(revision_t.c.id == revision_id))
            ).one_or_none()
        if f is None:
            return None
        return DetalleRevision(
            id=f.id,
            combate_id=f.combate_id,
            abierta_en=f.abierta_en,
            cerrada_en=f.cerrada_en,
            disponible=f.disponible,
            motivo_no_disp=f.motivo_no_disp,
            clase=clase_a_modelo(f.clase),
            tirador=f.tirador,
            confianza=_confianza(f),
            probabilidades=probabilidades_a_modelo(f.probabilidades),
            decision=f.decision,
            clase_final=clase_a_modelo(f.clase_final),
            registrado_en=f.registrado_en,
            auditoria_seq=f.auditoria_seq,
            auditoria_hash=f.auditoria_hash,
        )
