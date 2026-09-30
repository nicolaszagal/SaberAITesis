"""Exporta la evidencia de una sesión de validación (L02, T-017, RNF-03, RNF-06).

Calcula todo desde PostgreSQL y escribe, en `EVIDENCE_DIR/<evento_id>/`,
`resumen.json`, `revisiones.csv` (los 17 campos de L01) y `resumen.md`. El
JSONL de L01 solo se concilia contra la base; no se corrige.

Uso:
    cd backend && .venv/bin/python scripts/exportar_evidencia.py --evento <evento_id>

Variables: DATABASE_URL y EVIDENCE_DIR (obligatorias); M01_EXPERIMENT_LOG
(opcional) apunta a dataset/lstm_6class/EXPERIMENT_LOG.md. Es idempotente:
al reejecutarla se sobrescriben los tres archivos y solo cambia `generado_en`.
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
from fog.domain.errors import RecursoNoEncontrado  # noqa: E402
from fog.infrastructure.evidencia.exportador import ExportadorEvidencia  # noqa: E402
from shared import config  # noqa: E402


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--evento", required=True, type=uuid.UUID, help="id del evento")
    return parser.parse_args(argv)


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
        0 si se exportó; 1 si falta configuración o el evento no existe.
    """
    args = _argumentos(argv)
    try:
        config.require_paths("DATABASE_URL", "EVIDENCE_DIR")
        carpeta = asyncio.run(_exportar(args.evento))
    except (RuntimeError, RecursoNoEncontrado) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Evidencia exportada en {carpeta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
