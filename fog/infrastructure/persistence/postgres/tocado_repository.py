"""Adaptador SQLAlchemy de TocadoRepositoryPort sobre `sabre.tocado` y
`sabre.tocado_clip`.
"""

import uuid
from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Tocado
from fog.infrastructure.persistence.postgres.tables import tocado as tocado_tabla
from fog.infrastructure.persistence.postgres.tables import (
    tocado_clip as tocado_clip_tabla,
)
from fog.ports.tocado_repository import TocadoRepositoryPort


def _fila_a_tocado(fila: Row) -> Tocado:
    return Tocado(
        id=fila.id,
        combate_id=fila.combate_id,
        fuente=fila.fuente,
        luz_a=fila.luz_a,
        luz_b=fila.luz_b,
        t_tocado_utc=fila.t_tocado_utc,
        t_tocado_ms=fila.t_tocado_ms,
        registrado_por=fila.registrado_por,
        creado_en=fila.creado_en,
        t_luz_a_ms=fila.t_luz_a_ms,
        t_luz_b_ms=fila.t_luz_b_ms,
    )


class PostgresTocadoRepository(TocadoRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def crear(
        self,
        *,
        combate_id: uuid.UUID,
        fuente: str,
        luz_a: bool,
        luz_b: bool,
        t_tocado_utc: datetime | None = None,
        t_tocado_ms: int | None = None,
        t_luz_a_ms: int | None = None,
        t_luz_b_ms: int | None = None,
        registrado_por: uuid.UUID | None = None,
    ) -> Tocado:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(tocado_tabla)
                    .values(
                        id=uuid.uuid4(),
                        combate_id=combate_id,
                        fuente=fuente,
                        luz_a=luz_a,
                        luz_b=luz_b,
                        t_tocado_utc=t_tocado_utc,
                        t_tocado_ms=t_tocado_ms,
                        t_luz_a_ms=t_luz_a_ms,
                        t_luz_b_ms=t_luz_b_ms,
                        registrado_por=registrado_por,
                    )
                    .returning(tocado_tabla)
                )
            ).one()
        return _fila_a_tocado(fila)

    async def vincular_clip(
        self, tocado_id: uuid.UUID, clip_id: uuid.UUID, frame_tocado: int
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                insert(tocado_clip_tabla).values(
                    tocado_id=tocado_id, clip_id=clip_id, frame_tocado=frame_tocado
                )
            )

    async def obtener(self, tocado_id: uuid.UUID) -> Tocado | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(tocado_tabla).where(tocado_tabla.c.id == tocado_id)
                )
            ).one_or_none()
        return _fila_a_tocado(fila) if fila else None
