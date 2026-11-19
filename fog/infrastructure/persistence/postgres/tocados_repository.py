"""Adaptador SQLAlchemy de TocadosRepositoryPort (EDGE02)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.infrastructure.persistence.postgres.vocabulario import clase_a_esquema, clase_a_modelo
from fog.ports.tocados_repository import (
    ClipDeTocado,
    DecisionPista,
    TocadoListado,
    TocadosRepositoryPort,
)

_LISTA = """
SELECT t.id, t.combate_id, t.creado_en, t.fuente, t.luz_a, t.luz_b, t.t_luz_a_ms, t.t_luz_b_ms,
       tc.clip_id IS NOT NULL AS tiene_clip, cl.uri AS clip_uri,
       EXISTS (SELECT 1 FROM sabre.clasificacion c WHERE c.tocado_id = t.id) AS clasificado,
       (SELECT r.id FROM sabre.revision_var r WHERE r.tocado_id = t.id
         ORDER BY r.abierta_en DESC LIMIT 1) AS revision_id,
       EXISTS (SELECT 1 FROM sabre.tocado s WHERE s.combate_id = t.combate_id
                AND (s.creado_en, s.id) > (t.creado_en, t.id)) AS cerrado,
       d.clase AS dp_clase, d.anulado AS dp_anulado, d.registrado_en AS dp_en
FROM sabre.tocado t
LEFT JOIN sabre.tocado_clip tc ON tc.tocado_id = t.id
LEFT JOIN sabre.clip cl ON cl.id = tc.clip_id
LEFT JOIN LATERAL (SELECT clase, anulado, registrado_en FROM sabre.decision_pista dp
                    WHERE dp.tocado_id = t.id ORDER BY registrado_en DESC, id DESC LIMIT 1) d ON TRUE
"""


def _fila(f) -> TocadoListado:
    decision = (
        DecisionPista(clase_a_modelo(f.dp_clase), f.dp_anulado, f.dp_en) if f.dp_en is not None else None
    )
    return TocadoListado(
        id=f.id, combate_id=f.combate_id, creado_en=f.creado_en, fuente=f.fuente,
        luz_a=f.luz_a, luz_b=f.luz_b, t_luz_a_ms=f.t_luz_a_ms, t_luz_b_ms=f.t_luz_b_ms,
        tiene_clip=f.tiene_clip, clasificado=f.clasificado, revision_id=f.revision_id,
        cerrado=f.cerrado, decision_pista=decision, clip_uri=f.clip_uri,
    )


class PostgresTocadosRepository(TocadosRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def listar(self, combate_id: uuid.UUID, limite: int) -> list[TocadoListado]:
        async with self._session_factory() as session:
            filas = (
                await session.execute(
                    text(_LISTA + " WHERE t.combate_id = :c ORDER BY t.creado_en DESC, t.id DESC LIMIT :n"),
                    {"c": combate_id, "n": limite},
                )
            ).all()
        return [_fila(f) for f in filas]

    async def obtener(self, tocado_id: uuid.UUID) -> TocadoListado | None:
        async with self._session_factory() as session:
            fila = (await session.execute(text(_LISTA + " WHERE t.id = :t"), {"t": tocado_id})).first()
        return _fila(fila) if fila else None

    async def registrar_decision(
        self, tocado_id: uuid.UUID, *, clase: str | None, anulado: bool, registrado_por: uuid.UUID | None
    ) -> DecisionPista:
        async with self._session_factory() as session, session.begin():
            fila = (
                await session.execute(
                    text(
                        "INSERT INTO sabre.decision_pista (tocado_id, clase, anulado, registrado_por) "
                        "VALUES (:t, :c, :a, :u) RETURNING clase, anulado, registrado_en"
                    ),
                    {"t": tocado_id, "c": clase_a_esquema(clase), "a": anulado, "u": registrado_por},
                )
            ).one()
        return DecisionPista(clase_a_modelo(fila.clase), fila.anulado, fila.registrado_en)

    async def clip_de(self, tocado_id: uuid.UUID) -> ClipDeTocado | None:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    text(
                        "SELECT c.id, c.uri, c.sha256, c.fps FROM sabre.tocado_clip tc "
                        "JOIN sabre.clip c ON c.id = tc.clip_id WHERE tc.tocado_id = :t LIMIT 1"
                    ),
                    {"t": tocado_id},
                )
            ).first()
        return ClipDeTocado(fila.id, fila.uri, fila.sha256, float(fila.fps)) if fila else None

    async def uris_clips(
        self, combate_id: uuid.UUID | None = None, evento_id: uuid.UUID | None = None
    ) -> list[str]:
        sql = "SELECT uri FROM sabre.clip WHERE TRUE"
        params: dict = {}
        if combate_id is not None:
            sql += " AND combate_id = :c"
            params["c"] = combate_id
        if evento_id is not None:
            # El almacén direcciona por hash: un archivo que usa también un clip de otra sesión no se toca.
            sql += (
                " AND combate_id IN (SELECT id FROM sabre.combate WHERE evento_id = :e)"
                " AND uri NOT IN (SELECT uri FROM sabre.clip WHERE combate_id IS NULL OR combate_id NOT IN "
                "(SELECT id FROM sabre.combate WHERE evento_id = :e))"
            )
            params["e"] = evento_id
        async with self._session_factory() as session:
            return [f.uri for f in (await session.execute(text(sql), params)).all()]
