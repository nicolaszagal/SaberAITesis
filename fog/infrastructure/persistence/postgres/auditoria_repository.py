"""Adaptador SQLAlchemy de AuditoriaRepositoryPort sobre
`sabre.registro_auditoria`. Solo `registrar` (ver el puerto): hash y
encadenamiento los calcula el trigger `tg_auditoria_hash` en la base.
"""

import uuid

from sqlalchemy import insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Auditoria
from fog.infrastructure.persistence.postgres.tables import (
    registro_auditoria as auditoria_tabla,
)
from fog.ports.auditoria_repository import AuditoriaRepositoryPort


def _fila_a_auditoria(fila: Row) -> Auditoria:
    return Auditoria(
        seq=fila.seq,
        revision_id=fila.revision_id,
        snapshot=fila.snapshot,
        hash_prev=fila.hash_prev,
        hash=fila.hash,
        creado_en=fila.creado_en,
    )


class PostgresAuditoriaRepository(AuditoriaRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def registrar(self, *, revision_id: uuid.UUID, snapshot: dict) -> Auditoria:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(auditoria_tabla)
                    .values(revision_id=revision_id, snapshot=snapshot)
                    .returning(auditoria_tabla)
                )
            ).one()
        return _fila_a_auditoria(fila)
