"""Exporta la evidencia de una sesión de validación (L02, T-017, RNF-03, RNF-06).

Calcula todo desde PostgreSQL y escribe, en `EVIDENCE_DIR/<evento_id>/`,
`resumen.json`, `revisiones.csv` (los 18 campos de L01) y `resumen.md`. El
JSONL de L01 solo se concilia contra la base; no se corrige.

Uso:
    cd backend && .venv/bin/python scripts/exportar_evidencia.py --evento <evento_id>

Variables: DATABASE_URL y EVIDENCE_DIR (obligatorias); M01_EXPERIMENT_LOG
(opcional) apunta a dataset/lstm_6class/EXPERIMENT_LOG.md. Es idempotente:
al reejecutarla se sobrescriben los tres archivos y solo cambia `generado_en`.

Al terminar la exportación corre `scripts/respaldar_sesion.sh --evento` (FIX03), que exige
RESPALDO_DIR. Sin RESPALDO_DIR no respalda: lo avisa en grande y sale con 2. `--sin-respaldo`
omite el respaldo a propósito (pruebas).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fog.composition import Container  # noqa: E402
from fog.domain.errors import RecursoNoEncontrado  # noqa: E402
from fog.infrastructure.evidencia.exportador import ExportadorEvidencia  # noqa: E402
from shared import config  # noqa: E402


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--evento", required=True, type=uuid.UUID, help="id del evento")
    parser.add_argument(
        "--sin-respaldo", action="store_true", help="no respalda la base al terminar (no usar en una sesión real)"
    )
    return parser.parse_args(argv)


def _respaldar(evento_id: uuid.UUID) -> int:
    """Corre `scripts/respaldar_sesion.sh` o avisa en grande que falta el respaldo.

    Args:
        evento_id: evento cuya sesión se respalda.

    Returns:
        0 si el respaldo quedó verificado; 1 si el script falló; 2 si no hay RESPALDO_DIR
        (ni en el entorno ni en `.env`) y por eso no se respaldó.
    """
    if not os.environ.get("RESPALDO_DIR") and not _respaldo_dir_en_env():
        barra = "#" * 64
        print(
            f"\n{barra}\n#  SIN RESPALDO: RESPALDO_DIR no está definida.\n"
            "#  La evidencia se exportó, pero la base sigue en un único volumen (DEF-31).\n"
            f"#  Defina RESPALDO_DIR y corra: sh scripts/respaldar_sesion.sh --evento {evento_id}\n{barra}\n",
            file=sys.stderr,
        )
        return 2
    return subprocess.run(
        ["sh", str(BACKEND_DIR / "scripts" / "respaldar_sesion.sh"), "--evento", str(evento_id)],
        cwd=BACKEND_DIR,
        check=False,
    ).returncode


def _respaldo_dir_en_env() -> bool:
    ruta = BACKEND_DIR / os.environ.get("ENV_FILE", ".env")
    if not ruta.is_file():
        return False
    return any(
        linea.startswith("RESPALDO_DIR=") and linea.split("=", 1)[1].strip().strip("'\"")
        for linea in ruta.read_text().splitlines()
    )


async def _exportar(evento_id: uuid.UUID) -> Path:
    container = Container()
    container.config.database_url.from_value(config.DATABASE_URL)
    container.config.evidence_dir.from_value(config.EVIDENCE_DIR)
    container.config.m01_experiment_log.from_value(config.M01_EXPERIMENT_LOG)
    try:
        resultado = await container.resumir_validacion().execute(evento_id)
    finally:
        await container.db_engine().dispose()
    return ExportadorEvidencia(config.EVIDENCE_DIR).exportar(resultado)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del script.

    Args:
        argv: argumentos de línea de comandos (por defecto `sys.argv`).

    Returns:
        0 si se exportó y se respaldó; 1 si falta configuración, el evento no existe o el
        respaldo falló; 2 si se exportó pero no hay RESPALDO_DIR (sin respaldo).
    """
    args = _argumentos(argv)
    try:
        config.require_paths("DATABASE_URL", "EVIDENCE_DIR")
        carpeta = asyncio.run(_exportar(args.evento))
    except (RuntimeError, RecursoNoEncontrado) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Evidencia exportada en {carpeta}")
    return 0 if args.sin_respaldo else _respaldar(args.evento)


if __name__ == "__main__":
    sys.exit(main())
