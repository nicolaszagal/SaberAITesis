"""Análisis descriptivo del razonamiento en la Validación 1 (EXP03-b, D-17).

Para las revisiones del evento con clasificación disponible calcula el
razonamiento **en memoria** con los parámetros vigentes (no escribe en
`evidencia` ni en la auditoría) y escribe, en
`EVIDENCE_DIR/<evento_id>/razonamiento_v1.md`, la tabla de estados, causas de
`insuficiente`, censuras de U1 y U2 y distribución de `lock_frame`, junto a la de
una muestra de clips de entrenamiento. No es una métrica de aceptación.

Uso:
    cd backend && .venv/bin/python scripts/analizar_razonamiento_v1.py \\
        [--evento <evento_id>] \\
        [--muestra-train scripts/datos/muestra_train_razonamiento.json]

Sin `--evento` usa el evento "Validación 1". Variables: DATABASE_URL, STORAGE_DIR,
FEATURE_STATS_PATH y EVIDENCE_DIR (obligatorias). Es idempotente: reescribe el archivo.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fog.composition import Container  # noqa: E402
from fog.infrastructure.evidencia import informe_razonamiento  # noqa: E402
from shared import config  # noqa: E402

NOMBRE_EVENTO = "Validación 1"


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--evento", type=uuid.UUID, help="id del evento (por defecto, 'Validación 1')"
    )
    parser.add_argument(
        "--muestra-train", type=Path, help="JSON con la muestra de clips de train"
    )
    return parser.parse_args(argv)


async def _analizar(evento_id: uuid.UUID | None, muestra: Path | None) -> Path:
    container = Container()
    container.config.database_url.from_value(config.DATABASE_URL)
    container.config.storage_dir.from_value(config.STORAGE_DIR)
    container.config.feature_stats_path.from_value(config.FEATURE_STATS_PATH)
    container.config.feature_preprocessing_profile.from_value(
        config.FEATURE_PREPROCESSING_PROFILE
    )
    container.config.feature_preprocessing_profiles_path.from_value(
        config.FEATURE_PREPROCESSING_PROFILES_PATH
    )
    try:
        if evento_id is None:
            eventos = [
                e
                for e in await container.listar_eventos().execute()
                if e.nombre == NOMBRE_EVENTO
            ]
            if len(eventos) != 1:
                raise RuntimeError(
                    f"se esperaba un evento '{NOMBRE_EVENTO}' y hay {len(eventos)}"
                )
            evento_id = eventos[0].id
        analisis = await container.analizar_razonamiento().execute(evento_id)
    finally:
        await container.db_engine().dispose()
    train = informe_razonamiento.cargar_muestra_train(muestra) if muestra else None
    return informe_razonamiento.escribir(config.EVIDENCE_DIR, analisis, train)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del script.

    Args:
        argv: argumentos de línea de comandos (por defecto `sys.argv`).

    Returns:
        0 si se escribió el informe; 1 si falta configuración o el evento.
    """
    args = _argumentos(argv)
    try:
        config.require_paths(
            "DATABASE_URL", "STORAGE_DIR", "FEATURE_STATS_PATH", "EVIDENCE_DIR"
        )
        destino = asyncio.run(_analizar(args.evento, args.muestra_train))
    except (RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Informe escrito en {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
