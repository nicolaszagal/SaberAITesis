"""Adaptador SQLAlchemy de ClipRepositoryPort sobre `sabre.clip`."""

import uuid
from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Clip
from fog.infrastructure.persistence.postgres.tables import clip as clip_tabla
from fog.ports.clip_repository import ClipRepositoryPort


def _fila_a_clip(fila: Row) -> Clip:
    return Clip(
        id=fila.id,
        combate_id=fila.combate_id,
        origen=fila.origen,
        camara=fila.camara,
        uri=fila.uri,
        sha256=fila.sha256,
        fps=float(fila.fps),
        ancho_px=fila.ancho_px,
        alto_px=fila.alto_px,
        duracion_ms=fila.duracion_ms,
        t0_utc=fila.t0_utc,
        creado_en=fila.creado_en,
    )


class PostgresClipRepository(ClipRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def crear(
        self,
        *,
        combate_id: uuid.UUID,
        origen: str,
        camara: str,
        uri: str,
        sha256: str,
        fps: float,
        ancho_px: int,
        alto_px: int,
        duracion_ms: int,
        t0_utc: datetime | None = None,
    ) -> Clip:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(clip_tabla)
                    .values(
                        id=uuid.uuid4(),
                        combate_id=combate_id,
                        origen=origen,
                        camara=camara,
                        uri=uri,
                        sha256=sha256,
                        fps=fps,
                        ancho_px=ancho_px,
                        alto_px=alto_px,
                        duracion_ms=duracion_ms,
                        t0_utc=t0_utc,
                    )
                    .returning(clip_tabla)
                )
            ).one()
        return _fila_a_clip(fila)

    async def obtener(self, clip_id: uuid.UUID) -> Clip | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(clip_tabla).where(clip_tabla.c.id == clip_id)
                )
            ).one_or_none()
        return _fila_a_clip(fila) if fila else None
