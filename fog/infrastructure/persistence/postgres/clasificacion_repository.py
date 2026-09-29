"""Adaptador SQLAlchemy de ClasificacionRepositoryPort sobre
`sabre.clasificacion`. Sin update/delete (ver el puerto): el adaptador no
los implementa.
"""

import uuid

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Clasificacion
from fog.infrastructure.persistence.postgres.tables import (
    clasificacion as clasificacion_tabla,
)
from fog.ports.clasificacion_repository import ClasificacionRepositoryPort


def _fila_a_clasificacion(fila: Row) -> Clasificacion:
    return Clasificacion(
        id=fila.id,
        tocado_id=fila.tocado_id,
        modelo_version_id=fila.modelo_version_id,
        disponible=fila.disponible,
        motivo_no_disp=fila.motivo_no_disp,
        clase=fila.clase,
        tirador=fila.tirador,
        confianza=float(fila.confianza) if fila.confianza is not None else None,
        probabilidades=fila.probabilidades,
        keypoints_uri=fila.keypoints_uri,
        keypoints_sha256=fila.keypoints_sha256,
        features_uri=fila.features_uri,
        latencia_ms=fila.latencia_ms,
        creado_en=fila.creado_en,
    )


class PostgresClasificacionRepository(ClasificacionRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def crear(
        self,
        *,
        tocado_id: uuid.UUID,
        modelo_version_id: uuid.UUID,
        disponible: bool,
        keypoints_uri: str,
        keypoints_sha256: str,
        motivo_no_disp: str | None = None,
        clase: str | None = None,
        tirador: str | None = None,
        confianza: float | None = None,
        probabilidades: dict | None = None,
        features_uri: str | None = None,
        latencia_ms: int | None = None,
    ) -> Clasificacion:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(clasificacion_tabla)
                    .values(
                        id=uuid.uuid4(),
                        tocado_id=tocado_id,
                        modelo_version_id=modelo_version_id,
                        disponible=disponible,
                        motivo_no_disp=motivo_no_disp,
                        clase=clase,
                        tirador=tirador,
                        confianza=confianza,
                        probabilidades=probabilidades,
                        keypoints_uri=keypoints_uri,
                        keypoints_sha256=keypoints_sha256,
                        features_uri=features_uri,
                        latencia_ms=latencia_ms,
                    )
                    .returning(clasificacion_tabla)
                )
            ).one()
        return _fila_a_clasificacion(fila)

    async def obtener(self, clasificacion_id: uuid.UUID) -> Clasificacion | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(clasificacion_tabla).where(
                        clasificacion_tabla.c.id == clasificacion_id
                    )
                )
            ).one_or_none()
        return _fila_a_clasificacion(fila) if fila else None

    async def obtener_por_tocado_y_modelo(
        self, tocado_id: uuid.UUID, modelo_version_id: uuid.UUID
    ) -> Clasificacion | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(clasificacion_tabla).where(
                        clasificacion_tabla.c.tocado_id == tocado_id,
                        clasificacion_tabla.c.modelo_version_id == modelo_version_id,
                    )
                )
            ).one_or_none()
        return _fila_a_clasificacion(fila) if fila else None
