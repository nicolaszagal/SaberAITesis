"""Paridad entre el camino de entrenamiento y el de Fog (DEF-27).

Camino de entrenamiento: `process_clip` de dataset/05_extract_features.py
(YOLO `model.track`) + `_standardize_and_clamp` de dataset/lstm_6class/dataset.py.
Camino de Fog: YoloV8PoseAdapter + New192FeatureExtractor con el perfil
`lstm_6class` y las mismas estadísticas.

Ambos leen los mismos frames de 3 clips de dataset/dataset trimmed/test_trimmed.
Requiere YOLO y los archivos del dataset: `pytest -m slow`.
"""

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from fog.domain.models import WeaponSide
from fog.infrastructure.features.new192_feature_extractor import New192FeatureExtractor
from fog.infrastructure.features.preprocessing_profile import load_profile
from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter

pytestmark = pytest.mark.slow

DATASET = Path(__file__).resolve().parents[3] / "dataset"
CLIPS_DIR = DATASET / "dataset trimmed" / "test_trimmed"
POSE_MODEL = DATASET / "yolov8x-pose.pt"
STATS = DATASET / "lstm_6class" / "feature_stats.npz"
TOL = 1e-4

# Un clip por clase distinta; brazos distintos para cubrir ambas ramas de WEAPON_KPT.
CLIPS = [("AttackA", "AttackA_0007"), ("ContrattackB", None), ("RiposteA", None)]
SIDES = (WeaponSide.RIGHT, WeaponSide.LEFT)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pick_clips() -> list[Path]:
    picked = []
    for clase, stem in CLIPS:
        path = CLIPS_DIR / clase / f"{stem}.mp4" if stem else next(iter(sorted((CLIPS_DIR / clase).glob("*.mp4"))), None)
        if path is None or not path.exists():
            pytest.skip(f"clip de prueba no disponible en {CLIPS_DIR / clase}")
        picked.append(path)
    return picked


@pytest.fixture(scope="module")
def env():
    for required in (POSE_MODEL, STATS, CLIPS_DIR):
        if not required.exists():
            pytest.skip(f"falta {required}")
    from ultralytics import YOLO

    ef = _load_module("extract_features_train", DATASET / "05_extract_features.py")
    ds = _load_module("lstm6_dataset", DATASET / "lstm_6class" / "dataset.py")
    stats = np.load(STATS)
    # Instancias separadas: model.track() registra callbacks de tracking en el
    # predictor del modelo, que interferirían con el BOTSORT propio del adaptador.
    # El camino de entrenamiento carga una instancia nueva por clip (ver
    # _training_path); el adaptador de Fog se reutiliza, como en producción.
    return {
        "ef": ef,
        "ds": ds,
        "mean": stats["mean"].astype(np.float32),
        "std": stats["std"].astype(np.float32),
        "yolo_cls": YOLO,
        "fog_adapter": YoloV8PoseAdapter(YOLO(str(POSE_MODEL))),
        "extractor": New192FeatureExtractor(
            mean=stats["mean"], std=stats["std"], profile=load_profile("lstm_6class")
        ),
    }


def _training_path(env, clip: Path):
    ann = {"frame_inicio": 0, "frame_fin": 0, "luz_A": 0, "luz_B": 0,
           "weapon_side_A": SIDES[0].value, "weapon_side_B": SIDES[1].value}
    # Instancia nueva por clip: reutilizar la misma en 05_extract_features.py entre
    # clips desplaza las features hasta ~5e-3 respecto a una instancia limpia
    # (deriva del script de entrenamiento; Fog es determinista entre sesiones).
    model = env["yolo_cls"](str(POSE_MODEL))
    raw, stats = env["ef"].process_clip(str(clip), ann, model, 3, is_trimmed=True)
    assert raw is not None, stats
    norm = env["ds"]._standardize_and_clamp(raw.copy(), env["mean"], env["std"])
    for i in env["ds"].ABLATE_INDICES:
        norm[:, i] = 0.0
    return raw, norm


def _fog_path(env, clip: Path):
    session = env["fog_adapter"].start_session()
    cap = cv2.VideoCapture(str(clip))
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        session.add_frame(frame)
    cap.release()
    tracked = session.finish()
    extractor = env["extractor"]
    raw, _ = extractor.extract_raw(tracked, *SIDES)
    out = extractor.extract(tracked, *SIDES)
    assert out.sequence is not None, out.stats
    return raw, out.sequence


def _report(name: str, a: np.ndarray, b: np.ndarray) -> str:
    diff = np.abs(a - b)
    t, c = np.unravel_index(np.argmax(diff), diff.shape)
    return f"{name}: max|Δ|={diff.max():.3g} en frame {t}, columna {c}"


@pytest.mark.parametrize("clip", _pick_clips() if CLIPS_DIR.exists() else [], ids=lambda p: p.stem)
def test_fog_features_match_training_pipeline(env, clip):
    raw_ref, norm_ref = _training_path(env, clip)
    raw_fog, norm_fog = _fog_path(env, clip)

    assert raw_fog.shape == raw_ref.shape, f"frames: entrenamiento {raw_ref.shape} vs Fog {raw_fog.shape}"
    assert np.allclose(raw_fog, raw_ref, atol=TOL, rtol=0), _report("crudas", raw_fog, raw_ref)
    assert np.allclose(norm_fog, norm_ref, atol=TOL, rtol=0), _report("normalizadas", norm_fog, norm_ref)
