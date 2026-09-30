"""scripts/registrar_modelo.py: el registro es idempotente con
--solo-si-no-hay-activo (entrypoint de Fog en Docker), contra PostgreSQL real."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
RUN_ID = "20260101_000000"


def _cargar_script():
    spec = importlib.util.spec_from_file_location(
        "registrar_modelo", BACKEND / "scripts" / "registrar_modelo.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _dataset_falso(tmp_path: Path) -> Path:
    ckpt = tmp_path / "checkpoints" / RUN_ID
    ckpt.mkdir(parents=True)
    (ckpt / "run_config.json").write_text(json.dumps({"n_classes": 6}))
    (ckpt / "best_model.pt").write_bytes(b"pesos")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / f"{RUN_ID}_metrics.json").write_text(
        json.dumps({"f1_macro_sistema_best_loss": 0.5})
    )
    return tmp_path


async def test_solo_si_no_hay_activo_no_duplica_el_registro(
    tmp_path, session_factory
):
    registrar = _cargar_script().registrar_modelo
    dataset = _dataset_falso(tmp_path)

    primera = await registrar(
        RUN_ID, dataset_dir=dataset, pose_modelo="yolov8x-pose", activar=True,
        solo_si_no_hay_activo=True,
    )
    segunda = await registrar(
        RUN_ID, dataset_dir=dataset, pose_modelo="yolov8x-pose", activar=True,
        solo_si_no_hay_activo=True,
    )

    assert (primera, segunda) == (True, False)
    async with session_factory() as session:
        filas = (
            await session.execute(
                text("select count(*) from sabre.modelo_version where activo")
            )
        ).scalar_one()
    assert filas == 1
