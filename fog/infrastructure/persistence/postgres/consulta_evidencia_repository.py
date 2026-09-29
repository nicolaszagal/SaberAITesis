"""Adaptador SQLAlchemy de ConsultaEvidenciaRepositoryPort: lee de
`revision_var`, `veredicto`, `tocado`, `combate`, `clasificacion`,
`modelo_version` y `registro_auditoria` lo necesario para armar las líneas
de evidencia de un evento. Reutiliza los mapeos de fila de los repositorios
existentes, que traducen las clases del esquema al vocabulario del modelo.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.infrastructure.persistence.postgres.auditoria_repository import (
    _fila_a_auditoria,
)
from fog.infrastructure.persistence.postgres.clasificacion_repository import (
    _fila_a_clasificacion,
)
from fog.infrastructure.persistence.postgres.modelo_version_repository import (
    _fila_a_modelo_version,
)
from fog.infrastructure.persistence.postgres.revision_repository import (
    _fila_a_revision,
)
from fog.infrastructure.persistence.postgres.tables import (
    clasificacion as clasificacion_t,
)
from fog.infrastructure.persistence.postgres.tables import combate as combate_t
from fog.infrastructure.persistence.postgres.tables import evento as evento_t
from fog.infrastructure.persistence.postgres.tables import (
    modelo_version as modelo_t,
)
from fog.infrastructure.persistence.postgres.tables import (
    registro_auditoria as auditoria_t,
)
from fog.infrastructure.persistence.postgres.tables import revision_var as revision_t
from fog.infrastructure.persistence.postgres.tables import tocado as tocado_t
from fog.infrastructure.persistence.postgres.tables import veredicto as veredicto_t
from fog.infrastructure.persistence.postgres.tocado_repository import _fila_a_tocado
from fog.infrastructure.persistence.postgres.veredicto_repository import (
    _fila_a_veredicto,
)
from fog.ports.consulta_evidencia_repository import (
    ConsultaEvidenciaRepositoryPort,
    RevisionConVeredicto,
)


class PostgresConsultaEvidenciaRepository(ConsultaEvidenciaRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def existe_evento(self, evento_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            fila = (
                await session.execute(
                    select(evento_t.c.id).where(evento_t.c.id == evento_id)
                )
            ).first()
        return fila is not None

    async def listar_con_veredicto(
        self, evento_id: uuid.UUID
    ) -> list[RevisionConVeredicto]:
        async with self._session_factory() as session:
            filas = (
                await session.execute(
                    select(revision_t, veredicto_t.c.id.label("veredicto_id"))
                    .select_from(
                        revision_t.join(
                            veredicto_t, veredicto_t.c.revision_id == revision_t.c.id
                        )
                        .join(tocado_t, tocado_t.c.id == revision_t.c.tocado_id)
                        .join(combate_t, combate_t.c.id == tocado_t.c.combate_id)
                    )
                    .where(combate_t.c.evento_id == evento_id)
                )
            ).all()
            if not filas:
                return []
            revisiones = {f.id: _fila_a_revision(f) for f in filas}
            ids = list(revisiones)
            veredictos = {
                f.revision_id: _fila_a_veredicto(f)
                for f in (
                    await session.execute(
                        select(veredicto_t).where(veredicto_t.c.revision_id.in_(ids))
                    )
                ).all()
            }
            auditorias = {
                f.revision_id: _fila_a_auditoria(f)
                for f in (
                    await session.execute(
                        select(auditoria_t).where(auditoria_t.c.revision_id.in_(ids))
                    )
                ).all()
            }
            tocados = {
                f.id: _fila_a_tocado(f)
                for f in (
                    await session.execute(
                        select(tocado_t).where(
                            tocado_t.c.id.in_(
                                {r.tocado_id for r in revisiones.values()}
                            )
                        )
                    )
                ).all()
            }
            clasificaciones = {
                f.id: _fila_a_clasificacion(f)
                for f in (
                    await session.execute(
                        select(clasificacion_t).where(
                            clasificacion_t.c.id.in_(
                                {
                                    r.clasificacion_id
                                    for r in revisiones.values()
                                    if r.clasificacion_id is not None
                                }
                            )
                        )
                    )
                ).all()
            }
            modelos = {
                f.id: _fila_a_modelo_version(f)
                for f in (
                    await session.execute(
                        select(modelo_t).where(
                            modelo_t.c.id.in_(
                                {c.modelo_version_id for c in clasificaciones.values()}
                            )
                        )
                    )
                ).all()
            }
        resultado = []
        for revision_id, revision in revisiones.items():
            clasificacion = clasificaciones[revision.clasificacion_id]
            resultado.append(
                RevisionConVeredicto(
                    revision=revision,
                    tocado=tocados[revision.tocado_id],
                    clasificacion=clasificacion,
                    veredicto=veredictos[revision_id],
                    modelo=modelos[clasificacion.modelo_version_id],
                    auditoria=auditorias[revision_id],
                )
            )
        resultado.sort(key=lambda r: (r.veredicto.registrado_en, str(r.revision.id)))
        return resultado
