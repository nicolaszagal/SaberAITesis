"""Adaptador Postgres de UnidadDeTrabajoPort.

Reutiliza los repositorios existentes sin modificarlos: cada uno pide
`session_factory()` y abre `session.begin()`. Aquí se les entrega una
fábrica que devuelve siempre la misma sesión, con `begin()` neutro, para
que todos escriban dentro de la transacción única de la unidad de trabajo.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fog.infrastructure.persistence.postgres.auditoria_repository import (
    PostgresAuditoriaRepository,
)
from fog.infrastructure.persistence.postgres.clasificacion_repository import (
    PostgresClasificacionRepository,
)
from fog.infrastructure.persistence.postgres.clip_repository import (
    PostgresClipRepository,
)
from fog.infrastructure.persistence.postgres.combate_repository import (
    PostgresCombateRepository,
)
from fog.infrastructure.persistence.postgres.evento_repository import (
    PostgresEventoRepository,
)
from fog.infrastructure.persistence.postgres.modelo_version_repository import (
    PostgresModeloVersionRepository,
)
from fog.infrastructure.persistence.postgres.revision_repository import (
    PostgresRevisionRepository,
)
from fog.infrastructure.persistence.postgres.tirador_repository import (
    PostgresTiradorRepository,
)
from fog.infrastructure.persistence.postgres.tocado_repository import (
    PostgresTocadoRepository,
)
from fog.infrastructure.persistence.postgres.usuario_repository import (
    PostgresUsuarioRepository,
)
from fog.infrastructure.persistence.postgres.veredicto_repository import (
    PostgresVeredictoRepository,
)
from fog.ports.unidad_de_trabajo import Transaccion, UnidadDeTrabajoPort


class _SinTransaccionPropia:
    """`session.begin()` que no hace nada: la transacción ya está abierta."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _SesionCompartida:
    """Envuelve la sesión de la unidad de trabajo para que los repositorios
    la usen sin cerrarla ni abrir una transacción anidada."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def __aenter__(self) -> "_SesionCompartida":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    def begin(self) -> _SinTransaccionPropia:
        return _SinTransaccionPropia()

    def __getattr__(self, nombre: str):
        return getattr(self._session, nombre)


class PostgresUnidadDeTrabajo(UnidadDeTrabajoPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    @asynccontextmanager
    async def transaccion(self) -> AsyncIterator[Transaccion]:
        async with self._session_factory() as session, session.begin():
            compartida = lambda: _SesionCompartida(session)  # noqa: E731
            yield Transaccion(
                eventos=PostgresEventoRepository(compartida),
                usuarios=PostgresUsuarioRepository(compartida),
                tiradores=PostgresTiradorRepository(compartida),
                combates=PostgresCombateRepository(compartida),
                clips=PostgresClipRepository(compartida),
                tocados=PostgresTocadoRepository(compartida),
                modelos=PostgresModeloVersionRepository(compartida),
                clasificaciones=PostgresClasificacionRepository(compartida),
                revisiones=PostgresRevisionRepository(compartida),
                veredictos=PostgresVeredictoRepository(compartida),
                auditoria=PostgresAuditoriaRepository(compartida),
            )
