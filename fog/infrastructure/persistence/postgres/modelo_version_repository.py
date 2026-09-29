"""Adaptador SQLAlchemy de ModeloVersionRepositoryPort sobre
`sabre.modelo_version`.
"""

import uuid

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import ModeloVersion
from fog.infrastructure.persistence.postgres.tables import (
    modelo_version as modelo_version_tabla,
)
from fog.ports.modelo_version_repository import ModeloVersionRepositoryPort


def _fila_a_modelo_version(fila: Row) -> ModeloVersion:
    return ModeloVersion(
        id=fila.id,
        nombre=fila.nombre,
        checkpoint_uri=fila.checkpoint_uri,
        checkpoint_sha256=fila.checkpoint_sha256,
        pose_modelo=fila.pose_modelo,
        num_features=fila.num_features,
        num_clases=fila.num_clases,
        reglamento=fila.reglamento,
        f1_macro_test=float(fila.f1_macro_test)
        if fila.f1_macro_test is not None
        else None,
        kappa_piloto=float(fila.kappa_piloto)
        if fila.kappa_piloto is not None
        else None,
        padre_id=fila.padre_id,
        activo=fila.activo,
        creado_en=fila.creado_en,
    )


class PostgresModeloVersionRepository(ModeloVersionRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def registrar(
        self,
        *,
        nombre: str,
        checkpoint_uri: str,
        checkpoint_sha256: str,
        pose_modelo: str,
        num_features: int,
        num_clases: int,
        f1_macro_test: float | None = None,
        kappa_piloto: float | None = None,
        padre_id: uuid.UUID | None = None,
        activar: bool = True,
    ) -> ModeloVersion:
        async with self._session_factory() as session, session.begin():
            if activar:
                # Desactiva la versión activa anterior antes de insertar la
                # nueva: el índice único parcial ux_modelo_activo no admite
                # dos filas activo=true a la vez, ni siquiera transitoriamente
                # dentro de la misma transacción.
                await session.execute(
                    update(modelo_version_tabla)
                    .where(modelo_version_tabla.c.activo.is_(True))
                    .values(activo=False)
                )
            fila = (
                await session.execute(
                    insert(modelo_version_tabla)
                    .values(
                        id=uuid.uuid4(),
                        nombre=nombre,
                        checkpoint_uri=checkpoint_uri,
                        checkpoint_sha256=checkpoint_sha256,
                        pose_modelo=pose_modelo,
                        num_features=num_features,
                        num_clases=num_clases,
                        reglamento="FIE 2026",
                        f1_macro_test=f1_macro_test,
                        kappa_piloto=kappa_piloto,
                        padre_id=padre_id,
                        activo=activar,
                    )
                    .returning(modelo_version_tabla)
                )
            ).one()
        return _fila_a_modelo_version(fila)

    async def obtener_activo(self) -> ModeloVersion | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(modelo_version_tabla).where(
                        modelo_version_tabla.c.activo.is_(True)
                    )
                )
            ).one_or_none()
        return _fila_a_modelo_version(fila) if fila else None

    async def obtener(self, modelo_version_id: uuid.UUID) -> ModeloVersion | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(modelo_version_tabla).where(
                        modelo_version_tabla.c.id == modelo_version_id
                    )
                )
            ).one_or_none()
        return _fila_a_modelo_version(fila) if fila else None
