"""Adaptador SQLAlchemy de CombateRepositoryPort sobre `sabre.combate`."""

import uuid

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Combate
from fog.infrastructure.persistence.postgres.tables import combate as combate_tabla
from fog.ports.combate_repository import CombateRepositoryPort


def _fila_a_combate(fila: Row) -> Combate:
    return Combate(
        id=fila.id,
        evento_id=fila.evento_id,
        pista=fila.pista,
        fase=fila.fase,
        tirador_a_id=fila.tirador_a_id,
        tirador_b_id=fila.tirador_b_id,
        brazo_a=fila.brazo_a,
        brazo_b=fila.brazo_b,
        arbitro_id=fila.arbitro_id,
        configurado_por=fila.configurado_por,
        creado_en=fila.creado_en,
    )


class PostgresCombateRepository(CombateRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def crear(
        self,
        *,
        pista: str,
        tirador_a_id: uuid.UUID,
        tirador_b_id: uuid.UUID,
        brazo_a: str,
        brazo_b: str,
        arbitro_id: uuid.UUID,
        configurado_por: uuid.UUID,
        evento_id: uuid.UUID | None = None,
        fase: str | None = None,
    ) -> Combate:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(combate_tabla)
                    .values(
                        id=uuid.uuid4(),
                        evento_id=evento_id,
                        pista=pista,
                        fase=fase,
                        tirador_a_id=tirador_a_id,
                        tirador_b_id=tirador_b_id,
                        brazo_a=brazo_a,
                        brazo_b=brazo_b,
                        arbitro_id=arbitro_id,
                        configurado_por=configurado_por,
                    )
                    .returning(combate_tabla)
                )
            ).one()
        return _fila_a_combate(fila)

    async def obtener(self, combate_id: uuid.UUID) -> Combate | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(combate_tabla).where(combate_tabla.c.id == combate_id)
                )
            ).one_or_none()
        return _fila_a_combate(fila) if fila else None
