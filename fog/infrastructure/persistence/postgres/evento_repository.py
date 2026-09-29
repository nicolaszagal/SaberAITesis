"""Adaptador SQLAlchemy de EventoRepositoryPort sobre `sabre.evento`."""

import uuid
from datetime import date

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.audit_models import Evento
from fog.infrastructure.persistence.postgres.tables import evento as evento_tabla
from fog.ports.evento_repository import EventoRepositoryPort


def _fila_a_evento(fila: Row) -> Evento:
    return Evento(
        id=fila.id,
        nombre=fila.nombre,
        fecha=fila.fecha,
        lugar=fila.lugar,
        tipo=fila.tipo,
    )


class PostgresEventoRepository(EventoRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def crear(
        self, *, nombre: str, fecha: date, tipo: str, lugar: str | None = None
    ) -> Evento:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    insert(evento_tabla)
                    .values(
                        id=uuid.uuid4(),
                        nombre=nombre,
                        fecha=fecha,
                        tipo=tipo,
                        lugar=lugar,
                    )
                    .returning(evento_tabla)
                )
            ).one()
        return _fila_a_evento(fila)

    async def obtener(self, evento_id: uuid.UUID) -> Evento | None:
        async with self._session_factory() as session:
            consulta = select(evento_tabla).where(evento_tabla.c.id == evento_id)
            fila = (await session.execute(consulta)).one_or_none()
        return _fila_a_evento(fila) if fila else None
