"""CrearSesionValidacion — deja lista una sesión de validación piloto: el
evento (tipo `piloto`) y los usuarios árbitro y operador que la operan
(roles del esquema `sabre.usuario`). Es idempotente por nombre: lo que ya
existe se reutiliza y solo se crea lo que falta. Lo usa
`scripts/crear_sesion_validacion.py`; no forma parte de la API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fog.domain.audit_models import Evento, Usuario
from fog.domain.errors import ErrorDeDominio
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

TIPO_EVENTO = "piloto"
ROL_ARBITRO = "arbitro"
ROL_OPERADOR = "operador"


class EventoIncompatible(ErrorDeDominio):
    """Ya existe un evento con ese nombre pero no es de tipo `piloto`."""


@dataclass(frozen=True)
class SesionValidacion:
    """Resultado: filas de la sesión y si esta ejecución las creó."""

    evento: Evento
    arbitro: Usuario
    operador: Usuario
    evento_creado: bool
    arbitro_creado: bool
    operador_creado: bool


class CrearSesionValidacion:
    def __init__(self, uow: UnidadDeTrabajoPort):
        self._uow = uow

    async def execute(
        self, *, evento: str, fecha: date, arbitro: str, operador: str
    ) -> SesionValidacion:
        """Crea, si no existen, el evento piloto, el árbitro y el operador.

        Todo ocurre en una transacción: si algo falla no queda nada a medias.

        Args:
            evento: nombre del evento (clave de idempotencia).
            fecha: fecha con la que se crea el evento si no existe. Un evento
                existente conserva la suya.
            arbitro: nombre del árbitro (clave con el rol `arbitro`).
            operador: nombre del operador técnico (clave con el rol `operador`).

        Returns:
            La sesión con los tres registros y qué se creó en esta ejecución.

        Raises:
            EventoIncompatible: si el evento ya existe con otro tipo.
        """
        async with self._uow.transaccion() as tx:
            fila_evento = await tx.eventos.obtener_por_nombre(evento)
            if fila_evento is not None and fila_evento.tipo != TIPO_EVENTO:
                raise EventoIncompatible(
                    f"el evento {evento!r} ya existe con tipo {fila_evento.tipo!r}, "
                    f"no {TIPO_EVENTO!r}"
                )
            evento_creado = fila_evento is None
            if fila_evento is None:
                fila_evento = await tx.eventos.crear(
                    nombre=evento, fecha=fecha, tipo=TIPO_EVENTO
                )

            fila_arbitro = await tx.usuarios.obtener_por_nombre_y_rol(arbitro, ROL_ARBITRO)
            arbitro_creado = fila_arbitro is None
            if fila_arbitro is None:
                fila_arbitro = await tx.usuarios.crear(nombre=arbitro, rol=ROL_ARBITRO)

            fila_operador = await tx.usuarios.obtener_por_nombre_y_rol(operador, ROL_OPERADOR)
            operador_creado = fila_operador is None
            if fila_operador is None:
                fila_operador = await tx.usuarios.crear(nombre=operador, rol=ROL_OPERADOR)

        return SesionValidacion(
            evento=fila_evento,
            arbitro=fila_arbitro,
            operador=fila_operador,
            evento_creado=evento_creado,
            arbitro_creado=arbitro_creado,
            operador_creado=operador_creado,
        )
