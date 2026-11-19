"""Borra los clips de video de una sesión (D-22: ningún clip se conserva después de la sesión).

Herramienta manual; el cierre normal es el botón "Cerrar sesión de validación" (`POST /sesion/cerrar`), que
hace antes el respaldo verificado. Corre DESPUÉS de `exportar_evidencia.py` / `respaldar_sesion.sh` (el respaldo
excluye los clips y conserva `clip.sha256`, así que la auditoría sigue verificable).

Uso (con DATABASE_URL y STORAGE_DIR exportadas, p. ej. `set -a; source .env; set +a`):
    cd backend && .venv/bin/python scripts/purgar_clips.py --evento <uuid> --confirmar

Sin `--confirmar` solo cuenta lo que borraría. Un archivo que otra sesión también usa (mismo hash) no se borra.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fog.application.purgar_clips import PurgarClips  # noqa: E402
from fog.infrastructure.persistence.database import build_engine, build_session_factory  # noqa: E402
from fog.infrastructure.persistence.postgres.clip_repository import PostgresClipRepository  # noqa: E402
from fog.infrastructure.storage.local_file_storage import LocalFileStorage  # noqa: E402
from shared import config  # noqa: E402


async def _purgar(evento_id: uuid.UUID, borrar: bool) -> int:
    if not config.DATABASE_URL or not config.STORAGE_DIR:
        raise SystemExit("faltan DATABASE_URL o STORAGE_DIR")
    engine = build_engine(config.DATABASE_URL)
    try:
        repo = PostgresClipRepository(build_session_factory(engine))
        storage = LocalFileStorage(config.STORAGE_DIR)
        if borrar:
            return await PurgarClips(repo, storage).execute(evento_id)
        return sum(1 for uri in await repo.uris_de_sesion(evento_id) if storage.ruta_local(uri) is not None)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--evento", type=uuid.UUID, required=True, help="sesión (evento) cuyos clips se borran")
    parser.add_argument("--confirmar", action="store_true", help="borrar de verdad (sin esto solo cuenta)")
    args = parser.parse_args()
    n = asyncio.run(_purgar(args.evento, args.confirmar))
    print(f"clips {'borrados' if args.confirmar else 'por borrar (use --confirmar)'}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
