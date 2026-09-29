"""Adaptador SQLAlchemy de TiradorRepositoryPort sobre `sabre.tirador`."""

import uuid
from datetime import date

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Tirador
from fog.infrastructure.persistence.postgres.tables import tirador as tirador_tabla
from fog.ports.tirador_repository import TiradorRepositoryPort


def _fila_a_tirador(fila: Row) -> Tirador:
    return Tirador(
        id=fila.id,
        alias=fila.alias,
        brazo_habitual=fila.brazo_habitual,
        es_menor=fila.es_menor,
        consentimiento_firmado=fila.consentimiento_firmado,
        consentimiento_fecha=fila.consentimiento_fecha,
        firmante=fila.firmante,
        creado_en=fila.creado_en,
    )


class PostgresTiradorRepository(TiradorRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def crear(
        self,
        *,
        alias: str,
        brazo_habitual: str,
        es_menor: bool,
        consentimiento_firmado: bool = False,
        consentimiento_fecha: date | None = None,
        firmante: str | None = None,
    ) -> Tirador:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(tirador_tabla)
                    .values(
                        id=uuid.uuid4(),
                        alias=alias,
                        brazo_habitual=brazo_habitual,
                        es_menor=es_menor,
                        consentimiento_firmado=consentimiento_firmado,
                        consentimiento_fecha=consentimiento_fecha,
                        firmante=firmante,
                    )
                    .returning(tirador_tabla)
                )
            ).one()
        return _fila_a_tirador(fila)

    async def obtener(self, tirador_id: uuid.UUID) -> Tirador | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(tirador_tabla).where(tirador_tabla.c.id == tirador_id)
                )
            ).one_or_none()
        return _fila_a_tirador(fila) if fila else None
