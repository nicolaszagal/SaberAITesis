"""Borra los clips de video al cerrar la sesión (EDGE02: ningún clip se conserva).

Corre DESPUÉS de `exportar_evidencia.py` / `respaldar_sesion.sh` (el respaldo excluye los clips
y conserva `clip.sha256`, así que la auditoría sigue verificable). Borra:
  * los archivos de clip del almacén de Fog (`STORAGE_DIR`), con los URIs de la base;
  * los clips y JSON de Edge (`datos/edge/tocados/`).

Uso (con DATABASE_URL y STORAGE_DIR exportadas, p. ej. `set -a; source fog/.env; set +a`):
    cd backend && .venv/bin/python scripts/purgar_clips.py --confirmar [--edge-dir datos/edge/tocados]

Sin `--confirmar` solo cuenta lo que borraría. Salida: una línea con los conteos.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fog.application.purgar_clips import PurgarClips  # noqa: E402
from fog.infrastructure.persistence.database import build_engine, build_session_factory  # noqa: E402
from fog.infrastructure.persistence.postgres.tocados_repository import PostgresTocadosRepository  # noqa: E402
from fog.infrastructure.storage.local_file_storage import LocalFileStorage  # noqa: E402
from shared import config  # noqa: E402


def purgar_directorio_edge(directorio: Path, borrar: bool) -> int:
    """Cuenta (o borra) los MP4 y JSON de `tocado_*` de Edge."""
    archivos = [p for p in directorio.glob("tocado_*") if p.suffix in (".mp4", ".json")] if directorio.exists() else []
    if borrar:
        for p in archivos:
            p.unlink(missing_ok=True)
    return len(archivos)


async def _fog(borrar: bool) -> int:
    if not config.DATABASE_URL or not config.STORAGE_DIR:
        raise SystemExit("faltan DATABASE_URL o STORAGE_DIR (set -a; source fog/.env; set +a)")
    engine = build_engine(config.DATABASE_URL)
    try:
        repo = PostgresTocadosRepository(build_session_factory(engine))
        storage = LocalFileStorage(config.STORAGE_DIR)
        if borrar:
            return await PurgarClips(repo, storage).execute()
        return sum(1 for uri in set(await repo.uris_clips()) if storage.ruta_local(uri) is not None)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--confirmar", action="store_true", help="borrar de verdad (sin esto solo cuenta)")
    parser.add_argument("--edge-dir", type=Path, default=Path("datos/edge/tocados"))
    args = parser.parse_args()
    fog = asyncio.run(_fog(args.confirmar))
    edge = purgar_directorio_edge(args.edge_dir, args.confirmar)
    verbo = "borrados" if args.confirmar else "por borrar (use --confirmar)"
    print(f"clips de Fog {verbo}: {fog}; archivos de Edge {verbo}: {edge}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
