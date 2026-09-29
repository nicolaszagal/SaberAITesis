"""Humo end-to-end del pipeline de 6 clases: un clip real por clase de
dataset/dataset trimmed/test_trimmed, pasado por el mismo camino de
features que usa Fog en producción (YoloV8PoseAdapter + New192FeatureExtractor,
perfil `lstm_6class`) y clasificado con el checkpoint real desplegado
(MODEL_RUN_DIR, ver docs_claude/contexto_sabre.md sección 8).

No valida accuracy (el F1 macro documentado, 0.4856 ± 0.0322, ya está
reportado en dataset/lstm_6class/EXPERIMENT_LOG.md — RNF-03 no se cumple
todavía, decisión pendiente con el asesor): solo que el pipeline completo
corre sin excepciones, produce un RawVerdict válido por clip y reporta
tiempo de clasificación por clip. Requiere YOLO y el checkpoint real:
`pytest -m slow`.
"""

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from cloud.domain.models import CLASSES, LuzSignal
from cloud.infrastructure.classifier.lstm6class_adapter import LSTM6ClassAdapter
from fog.domain.models import WeaponSide
from fog.infrastructure.features.new192_feature_extractor import New192FeatureExtractor
from fog.infrastructure.features.preprocessing_profile import load_profile
from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter

pytestmark = pytest.mark.slow

DATASET = Path(__file__).resolve().parents[3] / "dataset"
CLIPS_DIR = DATASET / "dataset trimmed" / "test_trimmed"
POSE_MODEL = DATASET / "yolov8x-pose.pt"
STATS = DATASET / "lstm_6class" / "feature_stats.npz"
RUN_DIR = DATASET / "lstm_6class" / "checkpoints" / "20260928_141021"
SIDES = (WeaponSide.RIGHT, WeaponSide.LEFT)


def _pick_one_clip_per_class() -> list[tuple[str, Path]]:
    picked = []
    for clase in CLASSES:
        clips = sorted((CLIPS_DIR / clase).glob("*.mp4"))
        if not clips:
            pytest.skip(f"no hay clips de {clase} en {CLIPS_DIR}")
        picked.append((clase, clips[0]))
    return picked


@pytest.fixture(scope="module")
def env():
    for required in (POSE_MODEL, STATS, RUN_DIR, CLIPS_DIR):
        if not required.exists():
            pytest.skip(f"falta {required}")
    from ultralytics import YOLO

    stats = np.load(STATS)
    return {
        "fog_adapter": YoloV8PoseAdapter(YOLO(str(POSE_MODEL))),
        "extractor": New192FeatureExtractor(
            mean=stats["mean"], std=stats["std"], profile=load_profile("lstm_6class"),
        ),
        "classifier": LSTM6ClassAdapter(run_dir=str(RUN_DIR), device=torch.device("cpu")),
    }


def _extract_sequence(env, clip: Path) -> np.ndarray:
    session = env["fog_adapter"].start_session()
    cap = cv2.VideoCapture(str(clip))
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        session.add_frame(frame)
    cap.release()
    tracked = session.finish()
    out = env["extractor"].extract(tracked, *SIDES)
    assert out.sequence is not None, out.stats
    return out.sequence


def test_classifies_one_real_clip_per_class(env):
    resultados = []
    for clase, clip in _pick_one_clip_per_class():
        sequence = _extract_sequence(env, clip)

        luz = LuzSignal(has_luz_a=clase.endswith("A"), has_luz_b=clase.endswith("B"))
        start = time.perf_counter()
        raw = env["classifier"].classify(sequence, luz)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert raw.action_class.value in CLASSES
        assert 0.0 <= raw.confidence <= 1.0
        resultados.append((clase, clip.stem, raw.action_class.value, raw.confidence, elapsed_ms))

    print("\nclase_real       clip              pred              confianza  tiempo_ms")
    for clase, stem, pred, conf, ms in resultados:
        print(f"{clase:<16}  {stem:<16}  {pred:<16}  {conf:.3f}      {ms:.1f}")

    assert len(resultados) == len(CLASSES)
