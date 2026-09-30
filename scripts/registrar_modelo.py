"""Registra una corrida de entrenamiento como `sabre.modelo_version` (CU-13).

Lee `checkpoints/<run_id>/run_config.json` (num_clases) y
`results/<run_id>_metrics.json` (F1 macro) de `dataset/lstm_6class/`, y
calcula el SHA-256 de `checkpoints/<run_id>/best_model.pt` — el checkpoint
que se despliega (docs_claude/contexto_sabre.md sección 8: elegido por
mejor val_acc entre corridas, pero el archivo guardado es el de mejor
val_loss dentro de la corrida, de ahí "best_model.pt" y no
"best_acc_model.pt"). Por eso la métrica registrada es
`f1_macro_sistema_best_loss` (RNF-03 se reporta con el F1 macro "sistema",
es decir post filtro Favero — ver EXPERIMENT_LOG.md sección 8 de
contexto_sabre.md).

Uso:
    cd backend && .venv/bin/python scripts/registrar_modelo.py 20260928_141021

Activa la versión registrada por defecto (desactivando la anterior en la
misma transacción, ver ModeloVersionRepositoryPort.registrar); usar
--no-activar para solo dejarla registrada. Con --solo-si-no-hay-activo no
hace nada si ya existe una versión activa (lo usa el entrypoint de Fog en
Docker, para que reiniciar el contenedor no duplique el registro).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from fog.infrastructure.persistence.database import build_engine, build_session_factory  # noqa: E402
from fog.infrastructure.persistence.postgres.modelo_version_repository import (  # noqa: E402
    PostgresModeloVersionRepository,
)
from shared import config  # noqa: E402

NUM_FEATURES = 192  # New192FeatureExtractor / dataset/05_extract_features.py
POSE_MODELO = "yolov8x-pose"  # decisión de arquitectura, contexto_sabre.md sección 8
METRICA_F1_MACRO_TEST = "f1_macro_sistema_best_loss"  # ver docstring del módulo


def _sha256_de(ruta: Path) -> str:
    """Calcula el SHA-256 de un archivo en bloques (evita cargarlo entero en RAM).

    Args:
        ruta: archivo a hashear.

    Returns:
        Hash SHA-256 en hexadecimal (64 caracteres).
    """
    digest = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _leer_json(ruta: Path) -> dict:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}")
    return json.loads(ruta.read_text(encoding="utf-8"))


async def registrar_modelo(
    run_id: str,
    *,
    dataset_dir: Path,
    pose_modelo: str,
    activar: bool,
    solo_si_no_hay_activo: bool = False,
) -> bool:
    """Registra `run_id` como fila de `sabre.modelo_version`.

    Args:
        run_id: nombre de la corrida (subdirectorio de checkpoints/ y prefijo
            en results/).
        dataset_dir: raíz de `dataset/lstm_6class/` (checkpoints/ y results/).
        pose_modelo: valor de la columna `pose_modelo`.
        activar: si True, activa la versión registrada y desactiva la
            anterior en la misma transacción.
        solo_si_no_hay_activo: si True y ya hay una versión activa, no
            registra nada (idempotente).

    Returns:
        True si registró la versión; False si omitió el registro porque ya
        había una versión activa.

    Raises:
        FileNotFoundError: si falta run_config.json, metrics.json o el
            checkpoint.
        RuntimeError: si DATABASE_URL no está definida.
    """
    checkpoint_dir = dataset_dir / "checkpoints" / run_id
    run_config = _leer_json(checkpoint_dir / "run_config.json")
    metrics = _leer_json(dataset_dir / "results" / f"{run_id}_metrics.json")

    checkpoint_path = checkpoint_dir / "best_model.pt"
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"No existe {checkpoint_path}")

    num_clases = run_config["n_classes"]
    f1_macro_test = metrics.get(METRICA_F1_MACRO_TEST)

    engine = build_engine(config.DATABASE_URL, pooled=False)
    try:
        session_factory = build_session_factory(engine)
        repo = PostgresModeloVersionRepository(session_factory)
        if solo_si_no_hay_activo:
            activo = await repo.obtener_activo()
            if activo is not None:
                print(f"Ya hay un modelo activo ({activo.nombre}); no se registra {run_id}.")
                return False
        modelo = await repo.registrar(
            nombre=f"lstm6class-{run_id}",
            checkpoint_uri=str(checkpoint_path),
            checkpoint_sha256=_sha256_de(checkpoint_path),
            pose_modelo=pose_modelo,
            num_features=NUM_FEATURES,
            num_clases=num_clases,
            f1_macro_test=f1_macro_test,
            activar=activar,
        )
    finally:
        await engine.dispose()

    print(
        f"Registrado modelo_version {modelo.id} ({modelo.nombre}): "
        f"f1_macro_test={modelo.f1_macro_test} activo={modelo.activo}"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="p. ej. 20260928_141021")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=REPO_ROOT / "dataset" / "lstm_6class",
        help="Raíz de dataset/lstm_6class/ (default: sibling de backend/).",
    )
    parser.add_argument("--pose-modelo", default=POSE_MODELO)
    parser.add_argument(
        "--no-activar",
        action="store_false",
        dest="activar",
        help="Registra sin activar (por defecto activa y desactiva la anterior).",
    )
    parser.add_argument(
        "--solo-si-no-hay-activo",
        action="store_true",
        help="No registra nada si ya existe una versión activa (idempotente).",
    )
    args = parser.parse_args()

    asyncio.run(
        registrar_modelo(
            args.run_id,
            dataset_dir=args.dataset_dir,
            pose_modelo=args.pose_modelo,
            activar=args.activar,
            solo_si_no_hay_activo=args.solo_si_no_hay_activo,
        )
    )


if __name__ == "__main__":
    main()
