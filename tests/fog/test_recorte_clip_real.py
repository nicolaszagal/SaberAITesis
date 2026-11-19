"""DEF-32 con YOLO real: el clip original de 12 s ya no agota el plazo de 60 s (`pytest -m slow`)."""

from __future__ import annotations

import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import UploadFile

from fog.infrastructure.clips.clip_file_reader import process_uploaded_clip
from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter
from fog.infrastructure.storage.local_file_storage import LocalFileStorage

pytestmark = pytest.mark.slow

DATASET = Path(__file__).resolve().parents[3] / "dataset"
ORIGINAL = DATASET / "dataset raw" / "test" / "ContrattackA" / "ContrattackA_0071.mp4"
POSE_MODEL = DATASET / "yolov8x-pose.pt"
PLAZO_S = 60.0  # RNF-04 / D-08


def test_clip_original_de_12_s_se_recorta_y_termina_antes_de_60_s(tmp_path):
    if not ORIGINAL.exists() or not POSE_MODEL.exists():
        pytest.skip("faltan el clip original o los pesos de YOLO")
    from ultralytics import YOLO

    pose = YoloV8PoseAdapter(YOLO(str(POSE_MODEL)))
    storage = LocalFileStorage(tmp_path / "storage")
    contenido = ORIGINAL.read_bytes()
    t_tocado_ms = 8000  # instante dentro de los 12,2 s del original (366 fotogramas a 30 fps)

    t0 = time.monotonic()
    clip = asyncio.run(process_uploaded_clip(
        UploadFile(file=io.BytesIO(contenido), filename=ORIGINAL.name), pose, ThreadPoolExecutor(2), storage,
        clip_max_mb=200, min_frames=3, instantes_ms={"t_luz_a_ms": t_tocado_ms}, plazo_s=PLAZO_S,
    ))
    segundos = time.monotonic() - t0
    print(f"pose del clip recortado: {segundos:.1f} s, {len(clip.tracked.frames)} frames")

    assert segundos < PLAZO_S
    assert clip.desfase_recorte_ms == t_tocado_ms - 2000  # 2,0 s antes del tocado
    assert 70 <= len(clip.tracked.frames) <= 78  # 2,0 s + 0,5 s a 30 fps
    assert clip.duracion_ms == pytest.approx(2500, abs=70)
    assert t_tocado_ms - clip.desfase_recorte_ms == pytest.approx(2000, abs=34)  # el tocado cae a 2.000 ms
