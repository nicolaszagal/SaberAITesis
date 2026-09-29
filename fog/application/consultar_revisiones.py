"""ListarRevisiones, ObtenerRevision, VerificarAuditoria,
ObtenerModeloActivo y ConsultarSalud — consultas de solo lectura para la
interfaz. No modifican nada (RNF-01, RNF-05).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from fog.domain.audit_models import (
    DetalleRevision,
    ModeloVersion,
    RegistroAlterado,
    ResumenRevision,
)
from fog.domain.errors import RecursoNoEncontrado, SinModeloActivo
from fog.ports.consulta_revision_repository import ConsultaRevisionRepositoryPort
from fog.ports.modelo_version_repository import ModeloVersionRepositoryPort
from fog.ports.sonda_salud import SondaSaludPort
from fog.ports.verificador_auditoria import VerificadorAuditoriaPort


class ListarRevisiones:
    def __init__(self, consulta: ConsultaRevisionRepositoryPort):
        self._consulta = consulta

    async def execute(
        self,
        *,
        evento_id: uuid.UUID | None = None,
        desde: datetime | None = None,
        hasta: datetime | None = None,
    ) -> list[ResumenRevision]:
        """Lista las revisiones con filtros opcionales.

        Args:
            evento_id: solo las de combates de este evento.
            desde: solo las abiertas en o después de este instante.
            hasta: solo las abiertas en o antes de este instante.

        Returns:
            Resúmenes de la más reciente a la más antigua.
        """
        return await self._consulta.listar(evento_id=evento_id, desde=desde, hasta=hasta)


class ObtenerRevision:
    def __init__(self, consulta: ConsultaRevisionRepositoryPort):
        self._consulta = consulta

    async def execute(self, revision_id: uuid.UUID) -> DetalleRevision:
        """Devuelve el detalle de una revisión.

        Args:
            revision_id: id de la revisión.

        Returns:
            Sugerencia, probabilidades, veredicto y sello de auditoría.

        Raises:
            RecursoNoEncontrado: si la revisión no existe.
        """
        detalle = await self._consulta.detalle(revision_id)
        if detalle is None:
            raise RecursoNoEncontrado(f"revisión {str(revision_id)!r}")
        return detalle


class VerificarAuditoria:
    def __init__(self, verificador: VerificadorAuditoriaPort):
        self._verificador = verificador

    async def execute(self) -> list[RegistroAlterado]:
        """Verifica la cadena de hashes de la auditoría.

        Returns:
            Registros alterados; vacío si la cadena es íntegra.
        """
        return await self._verificador.verificar()


class ObtenerModeloActivo:
    def __init__(self, modelos: ModeloVersionRepositoryPort):
        self._modelos = modelos

    async def execute(self) -> ModeloVersion:
        """Devuelve la versión de modelo activa.

        Returns:
            La versión activa de `modelo_version`.

        Raises:
            SinModeloActivo: si no hay ninguna versión activa.
        """
        modelo = await self._modelos.obtener_activo()
        if modelo is None:
            raise SinModeloActivo()
        return modelo


@dataclass(frozen=True)
class EstadoSalud:
    fog: bool
    redis: bool
    postgres: bool

    @property
    def ok(self) -> bool:
        return self.fog and self.redis and self.postgres


class ConsultarSalud:
    def __init__(self, redis: SondaSaludPort, postgres: SondaSaludPort):
        self._redis = redis
        self._postgres = postgres

    async def execute(self) -> EstadoSalud:
        """Comprueba Redis y PostgreSQL. Fog está en `True` porque responde.

        Returns:
            El estado de cada componente.
        """
        return EstadoSalud(
            fog=True,
            redis=await self._redis.responde(),
            postgres=await self._postgres.responde(),
        )
