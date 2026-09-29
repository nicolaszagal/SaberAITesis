"""Adaptador SQLAlchemy de UsuarioRepositoryPort sobre `sabre.usuario`."""

import uuid

from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Usuario
from fog.infrastructure.persistence.postgres.tables import usuario as usuario_tabla
from fog.ports.usuario_repository import UsuarioRepositoryPort


def _fila_a_usuario(fila: Row) -> Usuario:
    return Usuario(
        id=fila.id,
        nombre=fila.nombre,
        rol=fila.rol,
        activo=fila.activo,
        creado_en=fila.creado_en,
    )


class PostgresUsuarioRepository(UsuarioRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def obtener(self, usuario_id: uuid.UUID) -> Usuario | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(usuario_tabla).where(usuario_tabla.c.id == usuario_id)
                )
            ).one_or_none()
        return _fila_a_usuario(fila) if fila else None
