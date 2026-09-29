"""Adaptador SQLAlchemy de RevisionRepositoryPort sobre `sabre.revision_var`."""

import uuid
from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Revision
from fog.infrastructure.persistence.postgres.tables import (
    revision_var as revision_tabla,
)
from fog.ports.revision_repository import RevisionRepositoryPort


def _fila_a_revision(fila: Row) -> Revision:
    return Revision(
        id=fila.id,
        tocado_id=fila.tocado_id,
        aceptada=fila.aceptada,
        arbitro_id=fila.arbitro_id,
        clasificacion_id=fila.clasificacion_id,
        abierta_en=fila.abierta_en,
        cerrada_en=fila.cerrada_en,
    )


class PostgresRevisionRepository(RevisionRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def crear(
        self, *, tocado_id: uuid.UUID, aceptada: bool, arbitro_id: uuid.UUID
    ) -> Revision:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(revision_tabla)
                    .values(
                        id=uuid.uuid4(),
                        tocado_id=tocado_id,
                        aceptada=aceptada,
                        arbitro_id=arbitro_id,
                    )
                    .returning(revision_tabla)
                )
            ).one()
        return _fila_a_revision(fila)

    async def obtener(self, revision_id: uuid.UUID) -> Revision | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(revision_tabla).where(revision_tabla.c.id == revision_id)
                )
            ).one_or_none()
        return _fila_a_revision(fila) if fila else None

    async def asignar_clasificacion(
        self, revision_id: uuid.UUID, clasificacion_id: uuid.UUID
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(revision_tabla)
                .where(revision_tabla.c.id == revision_id)
                .values(clasificacion_id=clasificacion_id)
            )

    async def cerrar(self, revision_id: uuid.UUID, cerrada_en: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(revision_tabla)
                .where(revision_tabla.c.id == revision_id)
                .values(cerrada_en=cerrada_en)
            )
