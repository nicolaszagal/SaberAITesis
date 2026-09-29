"""Crea la sesión de validación piloto: evento, árbitro y operador.

Crea el evento (tipo `piloto`) y los usuarios árbitro y operador (roles del
esquema `sabre.usuario`) y muestra sus ids, que la pantalla de configuración
necesita (`evento_id`, `arbitro_id` de POST /matches/config). Es idempotente
por nombre: si el evento o el usuario ya existen, se reutilizan y solo se
crea lo que falta.

Uso (con DATABASE_URL exportada, p. ej. `set -a; source fog/.env; set +a`):
    cd backend && .venv/bin/python scripts/crear_sesion_validacion.py \\
        --evento "Piloto 1" --fecha 2026-10-05 \\
        --arbitro "Nombre Árbitro" --operador "Nombre Operador"

Salida: una línea `clave: valor` por id, con `(creado)` o `(ya existía)`.
Código de salida 1 si el evento ya existe con un tipo distinto de `piloto`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fog.application.crear_sesion_validacion import (  # noqa: E402
    CrearSesionValidacion,
    EventoIncompatible,
    SesionValidacion,
)
from fog.infrastructure.persistence.database import (  # noqa: E402
    build_engine,
    build_session_factory,
)
from fog.infrastructure.persistence.postgres.unidad_de_trabajo import (  # noqa: E402
    PostgresUnidadDeTrabajo,
)
from shared import config  # noqa: E402


def _no_vacio(valor: str) -> str:
    valor = valor.strip()
    if not valor:
        raise argparse.ArgumentTypeError("no puede estar vacío")
    return valor


def _fecha(valor: str) -> date:
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{valor!r} no es una fecha YYYY-MM-DD") from None


async def crear_sesion(
    *, database_url: str | None, evento: str, fecha: date, arbitro: str, operador: str
) -> SesionValidacion:
    """Abre la base y ejecuta el caso de uso.

    Args:
        database_url: URL SQLAlchemy async (`postgresql+asyncpg://...`).
        evento: nombre del evento.
        fecha: fecha del evento si hay que crearlo.
        arbitro: nombre del árbitro.
        operador: nombre del operador.

    Returns:
        La sesión de validación resultante.

    Raises:
        RuntimeError: si `database_url` no está definida.
        EventoIncompatible: si el evento existe con un tipo distinto de `piloto`.
    """
    engine = build_engine(database_url, pooled=False)
    try:
        uow = PostgresUnidadDeTrabajo(build_session_factory(engine))
        return await CrearSesionValidacion(uow).execute(
            evento=evento, fecha=fecha, arbitro=arbitro, operador=operador
        )
    finally:
        await engine.dispose()


def _marca(creado: bool) -> str:
    return "(creado)" if creado else "(ya existía)"


def mostrar(sesion: SesionValidacion, fecha_pedida: date) -> None:
    """Imprime los ids de la sesión, y avisa si el evento conserva otra fecha."""
    print(f"evento_id: {sesion.evento.id} {_marca(sesion.evento_creado)}")
    print(f"arbitro_id: {sesion.arbitro.id} {_marca(sesion.arbitro_creado)}")
    print(f"operador_id: {sesion.operador.id} {_marca(sesion.operador_creado)}")
    if not sesion.evento_creado and sesion.evento.fecha != fecha_pedida:
        print(
            f"AVISO: el evento ya existía con fecha {sesion.evento.fecha}; "
            f"se pidió {fecha_pedida} y no se modificó.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--evento", required=True, type=_no_vacio, help="Nombre del evento piloto.")
    parser.add_argument("--fecha", required=True, type=_fecha, help="Fecha del evento, YYYY-MM-DD.")
    parser.add_argument("--arbitro", required=True, type=_no_vacio, help="Nombre del árbitro.")
    parser.add_argument("--operador", required=True, type=_no_vacio, help="Nombre del operador técnico.")
    args = parser.parse_args()

    try:
        sesion = asyncio.run(
            crear_sesion(
                database_url=config.DATABASE_URL,
                evento=args.evento,
                fecha=args.fecha,
                arbitro=args.arbitro,
                operador=args.operador,
            )
        )
    except (RuntimeError, EventoIncompatible) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    mostrar(sesion, args.fecha)


if __name__ == "__main__":
    main()
