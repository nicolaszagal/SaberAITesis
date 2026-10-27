"""Adaptador SQLAlchemy de RazonamientoRepositoryPort sobre `sabre.evidencia`."""

import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.domain.razonamiento import (
    TIPO_CRITERIO,
    TIPO_DESPLAZAMIENTO,
    TIPO_EXTENSION,
    TIPO_FRAME_CLAVE,
    TIPO_TOCADO,
    FilaEvidencia,
)
from fog.infrastructure.persistence.postgres.tables import evidencia as evidencia_tabla
from fog.ports.razonamiento_repository import RazonamientoRepositoryPort

_ORDEN_TIPOS = [
    TIPO_TOCADO,
    TIPO_EXTENSION,
    TIPO_DESPLAZAMIENTO,
    TIPO_FRAME_CLAVE,
    TIPO_CRITERIO,
]


class PostgresRazonamientoRepository(RazonamientoRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def registrar(
        self, clasificacion_id: uuid.UUID, filas: list[FilaEvidencia]
    ) -> None:
        if not filas:
            return
        async with self._session_factory() as session, session.begin():
            await session.execute(
                insert(evidencia_tabla),
                [
                    {
                        "id": uuid.uuid4(),
                        "clasificacion_id": clasificacion_id,
                        "tipo": f.tipo,
                        "tirador": f.tirador,
                        "frame_idx": f.frame_idx,
                        "t_ms": f.t_ms,
                        "articulo_fie": f.articulo_fie,
                        "detalle": f.detalle,
                    }
                    for f in filas
                ],
            )

    async def listar(self, clasificacion_id: uuid.UUID) -> list[FilaEvidencia]:
        async with self._session_factory() as session:
            filas = (
                await session.execute(
                    select(evidencia_tabla).where(
                        evidencia_tabla.c.clasificacion_id == clasificacion_id
                    )
                )
            ).all()
        # La tabla no guarda el orden de inserción: se devuelve en orden fijo.
        return sorted(
            (
                FilaEvidencia(
                    f.tipo, f.tirador, f.frame_idx, f.t_ms, f.articulo_fie, f.detalle
                )
                for f in filas
            ),
            key=lambda f: (_ORDEN_TIPOS.index(f.tipo), f.tirador or ""),
        )
