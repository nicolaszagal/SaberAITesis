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
    nube: bool  # Redis (transporte local) o Cloud por HTTP (DEPLOY11)
    postgres: bool
    nombre_nube: str = "redis"  # "redis" o "cloud": clave con la que `/health` informa `nube`

    @property
    def ok(self) -> bool:
        return self.fog and self.nube and self.postgres


class ConsultarSalud:
    def __init__(self, nube: SondaSaludPort, postgres: SondaSaludPort, nombre_nube: str = "redis"):
        """Crea la consulta.

        Args:
            nube: sonda de lo que lleva las features a Cloud (Redis o la API HTTP de Cloud).
            postgres: sonda de PostgreSQL.
            nombre_nube: `redis` o `cloud`, el nombre del componente en `/health`.
        """
        self._nube = nube
        self._postgres = postgres
        self._nombre_nube = nombre_nube

    async def execute(self) -> EstadoSalud:
        """Comprueba el transporte hacia Cloud y PostgreSQL. Fog está en `True` porque responde.

        Returns:
            El estado de cada componente.
        """
        return EstadoSalud(
            fog=True,
            nube=await self._nube.responde(),
            postgres=await self._postgres.responde(),
            nombre_nube=self._nombre_nube,
        )
