"""Adaptador SQLAlchemy de VeredictoRepositoryPort sobre `sabre.veredicto`.
Sin update/delete (ver el puerto): el adaptador no los implementa.
"""

import uuid

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Veredicto
from fog.infrastructure.persistence.postgres.tables import veredicto as veredicto_tabla
from fog.ports.veredicto_repository import VeredictoRepositoryPort


def _fila_a_veredicto(fila: Row) -> Veredicto:
    return Veredicto(
        id=fila.id,
        revision_id=fila.revision_id,
        decision=fila.decision,
        clase_final=fila.clase_final,
        arbitro_id=fila.arbitro_id,
        registrado_en=fila.registrado_en,
    )


class PostgresVeredictoRepository(VeredictoRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def crear(
        self,
        *,
        revision_id: uuid.UUID,
        decision: str,
        arbitro_id: uuid.UUID,
        clase_final: str | None = None,
    ) -> Veredicto:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(veredicto_tabla)
                    .values(
                        id=uuid.uuid4(),
                        revision_id=revision_id,
                        decision=decision,
                        clase_final=clase_final,
                        arbitro_id=arbitro_id,
                    )
                    .returning(veredicto_tabla)
                )
            ).one()
        return _fila_a_veredicto(fila)

    async def obtener_por_revision(self, revision_id: uuid.UUID) -> Veredicto | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(veredicto_tabla).where(
                        veredicto_tabla.c.revision_id == revision_id
                    )
                )
            ).one_or_none()
        return _fila_a_veredicto(fila) if fila else None
