"""ConsultarRazonamiento — F-035, CU-09, D-16, D-17: sirve el razonamiento que
Fog guardó al clasificar. Solo lectura: no recalcula nada, así lo que ve el
árbitro es lo que quedó registrado.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fog.domain.errors import ClasificacionPendiente, RecursoNoEncontrado
from fog.domain.razonamiento import TIPO_CRITERIO, TIPO_FRAME_CLAVE, FilaEvidencia
from fog.ports.consulta_revision_repository import ConsultaRevisionRepositoryPort
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

NO_REGISTRADO = "no_registrado"
NO_DISPONIBLE = "no_disponible"


@dataclass(frozen=True)
class VistaRazonamiento:
    """Razonamiento de una revisión.

    `estado` es uno de `respaldada`, `discordante`, `no_concluyente`,
    `insuficiente`, `no_registrado` (revisión anterior al registro, D-17) o
    `no_disponible` (sin sugerencia; `motivo` trae el `motivo_no_disp`).
    """

    revision_id: uuid.UUID
    estado: str
    frases: list[str] = field(default_factory=list)
    articulo: str | None = None
    clase: str | None = None
    confianza: float | None = None
    ventana_atencion: dict | None = None
    frame_clave: int | None = None
    eventos: list[FilaEvidencia] = field(default_factory=list)
    params_version: str | None = None
    motivo: str | None = None


class ConsultarRazonamiento:
    def __init__(
        self, consulta: ConsultaRevisionRepositoryPort, uow: UnidadDeTrabajoPort
    ):
        self._consulta = consulta
        self._uow = uow

    async def execute(self, revision_id: uuid.UUID) -> VistaRazonamiento:
        """Arma la vista del razonamiento de una revisión.

        Args:
            revision_id: id de la revisión.

        Returns:
            La vista; con la clasificación no disponible, `no_disponible`; sin
            filas de evidencia, `no_registrado`.

        Raises:
            RecursoNoEncontrado: si la revisión no existe.
            ClasificacionPendiente: si la revisión aún no tiene clasificación.
        """
        datos = await self._consulta.datos_razonamiento(revision_id)
        if datos is None:
            raise RecursoNoEncontrado(f"revisión {str(revision_id)!r}")
        if datos.clasificacion_id is None:
            raise ClasificacionPendiente()
        if not datos.disponible:
            return VistaRazonamiento(
                revision_id=revision_id,
                estado=NO_DISPONIBLE,
                motivo=datos.motivo_no_disp,
            )
        async with self._uow.transaccion() as tx:
            filas = await tx.razonamientos.listar(datos.clasificacion_id)
        criterio = next((f for f in filas if f.tipo == TIPO_CRITERIO), None)
        if criterio is None:
            return VistaRazonamiento(
                revision_id=revision_id,
                estado=NO_REGISTRADO,
                clase=datos.clase,
                confianza=datos.confianza,
            )
        clave = next((f for f in filas if f.tipo == TIPO_FRAME_CLAVE), None)
        return VistaRazonamiento(
            revision_id=revision_id,
            estado=criterio.detalle["estado"],
            frases=list(criterio.detalle["frases"]),
            articulo=criterio.articulo_fie,
            clase=datos.clase,
            confianza=datos.confianza,
            ventana_atencion=criterio.detalle.get("ventana_atencion"),
            frame_clave=clave.frame_idx if clave else None,
            eventos=[
                f for f in filas if f.tipo not in (TIPO_CRITERIO, TIPO_FRAME_CLAVE)
            ],
            params_version=criterio.detalle["params_version"],
        )
