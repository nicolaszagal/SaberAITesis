"""Prueba de sensibilidad de features: camino de entrenamiento vs camino de Fog.

Compara, sobre los 104 clips de test de `dataset/lstm_6class`, las
predicciones del checkpoint desplegado (`20260928_141021/best_model.pt`,
ver `docs_claude/contexto_sabre.md` sección 8) usando dos caminos de
extracción de features:

  - "dataset": las features ya guardadas en `dataset/features/test/*.npy`
    (las mismas que generaron `results/20260928_141021_predictions.csv`).
  - "fog": `YoloV8PoseAdapter` + `New192FeatureExtractor` (perfil
    `lstm_6class`), extraídas en vivo desde los clips de
    `dataset/dataset trimmed/test_trimmed`.

No modifica nada bajo `dataset/`: solo lee `.npy`, `.mp4`, `feature_stats.npz`
y `luz_annotations.csv`. El filtro Favero se aplica con la misma lógica que
`apply_favero_logit_mask` de `dataset/lstm_6class/evaluate.py`, reproducida
en este script (no importada: evaluate.py importa pandas, que no está
instalado en backend/.venv; evaluate.py no se modificó).

Uso:
    cd backend && .venv/bin/python scripts/sensibilidad_features.py

Salida:
    backend/docs/evidencia/sensibilidad_features.md
"""

# ruff: noqa: E402  # imports van después de ajustar sys.path (necesario
# para resolver `fog`, `dataset` y `model` sin instalar backend/dataset/lstm_6class
# como paquetes).

from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"
LSTM6_DIR = DATASET_DIR / "lstm_6class"

# Orden importante: LSTM6_DIR primero para que `import dataset` resuelva
# a dataset/lstm_6class/dataset.py y no a un paquete de otro nombre bajo
# backend/.
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(LSTM6_DIR))

from model import LSTMClassifier

from dataset import (
    A_SIDE_INDICES,
    B_SIDE_INDICES,
    CLASSES,
    _standardize_and_clamp,
)
from fog.domain.models import WeaponSide
from fog.infrastructure.features.new192_feature_extractor import (
    New192FeatureExtractor,
)
from fog.infrastructure.features.preprocessing_profile import load_profile
from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter


def apply_favero_logit_mask(logits_batch: torch.Tensor, luz_batch: torch.Tensor) -> torch.Tensor:
    """Idéntica a `apply_favero_logit_mask` de `dataset/lstm_6class/evaluate.py`
    (reproducida acá, no importada, porque evaluate.py importa pandas y
    backend/.venv no lo tiene instalado; evaluate.py no se modificó)."""
    masked = logits_batch.clone()
    for i in range(len(luz_batch)):
        luz_A, luz_B = luz_batch[i, 0].item(), luz_batch[i, 1].item()
        if luz_A > 0.5 and luz_B < 0.5:
            for j in B_SIDE_INDICES:
                masked[i, j] = float("-inf")
        elif luz_B > 0.5 and luz_A < 0.5:
            for j in A_SIDE_INDICES:
                masked[i, j] = float("-inf")
    return masked


def compute_per_class_metrics(preds, labels):
    """Idéntica a `compute_per_class_metrics` de `evaluate.py` (ver nota arriba)."""
    preds, labels = np.asarray(preds), np.asarray(labels)
    per_class = {}
    f1s = []
    for i, cls in enumerate(CLASSES):
        tp = int(((preds == i) & (labels == i)).sum())
        fp = int(((preds == i) & (labels != i)).sum())
        fn = int(((preds != i) & (labels == i)).sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        support = int((labels == i).sum())
        per_class[cls] = {"precision": round(prec, 4), "recall": round(rec, 4),
                           "f1": round(f1, 4), "support": support, "tp": tp, "fp": fp, "fn": fn}
        f1s.append(f1)
    acc = float((preds == labels).mean())
    return acc, float(np.mean(f1s)), per_class

RUN_ID = "20260928_141021"
CLIPS_DIR = DATASET_DIR / "dataset trimmed" / "test_trimmed"
FEATURES_TEST_DIR = DATASET_DIR / "features" / "test"
STATS_PATH = LSTM6_DIR / "feature_stats.npz"
LUZ_PATH = DATASET_DIR / "labels" / "luz_annotations.csv"
POSE_MODEL_PATH = DATASET_DIR / "yolov8x-pose.pt"
CHECKPOINT_DIR = LSTM6_DIR / "checkpoints" / RUN_ID
RESULTS_CSV = LSTM6_DIR / "results" / f"{RUN_ID}_predictions.csv"
REPORT_PATH = BACKEND_DIR / "docs" / "evidencia" / "sensibilidad_features.md"

# MVP: ambos tiradores usan "right" (ver docstring de dataset/05_extract_features.py,
# "Para el MVP ambos tiradores usan 'right'"). No hay weapon_side_A/B real
# anotado para el path de Fog en esta prueba.
WEAPON_SIDE_A = WeaponSide.RIGHT
WEAPON_SIDE_B = WeaponSide.RIGHT


def load_luz_map() -> dict[str, tuple[bool, bool]]:
    luz = {}
    with open(LUZ_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            luz[row["stem"]] = (int(row["luz_A"]) > 0, int(row["luz_B"]) > 0)
    return luz


def load_stored_predictions() -> dict[str, dict]:
    rows = {}
    with open(RESULTS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["stem"]] = row
    return rows


def discover_clips() -> list[tuple[str, str, Path, Path]]:
    """Los 104 stems de dataset/features/test/, con su .mp4 en test_trimmed/.

    Se recorre features/test/ (no test_trimmed/) porque test_trimmed/ tiene
    un clip de más (AttackB_0116) sin feature extraída — no forma parte de
    los 104 clips que generaron results/{RUN_ID}_predictions.csv.
    """
    clips = []
    for cls in CLASSES:
        folder = FEATURES_TEST_DIR / cls
        if not folder.is_dir():
            continue
        for npy_path in sorted(folder.glob("*.npy")):
            stem = npy_path.stem
            mp4_path = CLIPS_DIR / cls / f"{stem}.mp4"
            clips.append((cls, stem, npy_path, mp4_path))
    return clips


def build_model(config: dict) -> LSTMClassifier:
    model = LSTMClassifier(
        input_size=192,
        hidden_size=config["hidden_size"],
        num_layers=config["num_layers"],
        num_classes=len(CLASSES),
        dropout=0.0,
        luz_size=config["luz_size"],
        use_attention=config["use_attention"],
    )
    state = torch.load(CHECKPOINT_DIR / "best_model.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.eval()
    return model


def classify(model: LSTMClassifier, sequence: np.ndarray, luz_ab: tuple[bool, bool]) -> str:
    x = torch.tensor(sequence, dtype=torch.float32).unsqueeze(0)
    lengths = torch.tensor([sequence.shape[0]])
    luz = torch.tensor([[float(luz_ab[0]), float(luz_ab[1])]], dtype=torch.float32)
    with torch.no_grad():
        logits = model(x, lengths, luz)
    masked = apply_favero_logit_mask(logits, luz)
    return CLASSES[int(masked.argmax(dim=1).item())]


def extract_fog_normalized(adapter: YoloV8PoseAdapter, extractor: New192FeatureExtractor,
                            mp4_path: Path) -> tuple[np.ndarray | None, str | None]:
    """Corre el camino de Fog sobre un clip. Retorna (secuencia normalizada, error)."""
    session = adapter.start_session()
    cap = cv2.VideoCapture(str(mp4_path))
    if not cap.isOpened():
        return None, "no se pudo abrir el video"
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            session.add_frame(frame)
    finally:
        cap.release()
    tracked = session.finish()
    out = extractor.extract(tracked, WEAPON_SIDE_A, WEAPON_SIDE_B)
    if out.sequence is None:
        return None, out.stats.get("error", "error desconocido")
    return out.sequence, None


def main() -> None:
    import json

    with open(CHECKPOINT_DIR / "run_config.json") as f:
        config = json.load(f)

    stats = np.load(STATS_PATH)
    mean, std = stats["mean"].astype(np.float32), stats["std"].astype(np.float32)

    luz_map = load_luz_map()
    stored_predictions = load_stored_predictions()
    clips = discover_clips()

    model = build_model(config)

    from ultralytics import YOLO

    adapter = YoloV8PoseAdapter(YOLO(str(POSE_MODEL_PATH)))
    extractor = New192FeatureExtractor(mean=stats["mean"], std=stats["std"],
                                        profile=load_profile("lstm_6class"))

    rows = []
    failures = []

    for i, (cls, stem, npy_path, mp4_path) in enumerate(clips, start=1):
        print(f"[{i}/{len(clips)}] {stem}", flush=True)

        if stem not in stored_predictions:
            failures.append((stem, f"no está en results/{RUN_ID}_predictions.csv"))
            continue
        if not mp4_path.exists():
            failures.append((stem, f"clip no encontrado en {mp4_path}"))
            continue

        raw_stored = np.load(npy_path).astype(np.float32)
        norm_stored = _standardize_and_clamp(raw_stored.copy(), mean, std)

        luz_ab = luz_map.get(stem, (False, False))

        norm_fog, err = extract_fog_normalized(adapter, extractor, mp4_path)
        if norm_fog is None:
            failures.append((stem, err))
            continue

        pred_dataset = classify(model, norm_stored, luz_ab)
        pred_fog = classify(model, norm_fog, luz_ab)
        pred_stored_csv = stored_predictions[stem]["pred_sistema"]
        true_label = stored_predictions[stem]["true_label"]

        if norm_fog.shape != norm_stored.shape:
            diff_max = diff_mean = float("nan")
            shape_note = f"shapes distintos: dataset {norm_stored.shape} vs fog {norm_fog.shape}"
        else:
            diff = np.abs(norm_stored - norm_fog)
            diff_max = float(diff.max())
            diff_mean = float(diff.mean())
            shape_note = ""

        rows.append({
            "stem": stem, "clase": cls, "true_label": true_label,
            "pred_stored_csv": pred_stored_csv,
            "pred_dataset_repro": pred_dataset,
            "pred_fog": pred_fog,
            "match_dataset_vs_csv": pred_dataset == pred_stored_csv,
            "match_fog_vs_csv": pred_fog == pred_stored_csv,
            "diff_max": diff_max, "diff_mean": diff_mean,
            "shape_note": shape_note,
        })

    write_report(rows, failures, config)
    print(f"\nOK {REPORT_PATH} ({len(rows)} clips comparados, {len(failures)} fallas)")


def write_report(rows: list[dict], failures: list[tuple[str, str]], config: dict) -> None:
    labels = [CLASSES.index(r["true_label"]) for r in rows]

    idx_dataset = [CLASSES.index(r["pred_dataset_repro"]) for r in rows]
    idx_fog = [CLASSES.index(r["pred_fog"]) for r in rows]
    idx_csv = [CLASSES.index(r["pred_stored_csv"]) for r in rows]

    acc_dataset, f1_dataset, _ = compute_per_class_metrics(idx_dataset, labels)
    acc_fog, f1_fog, _ = compute_per_class_metrics(idx_fog, labels)
    acc_csv, f1_csv, _ = compute_per_class_metrics(idx_csv, labels)

    n_match_dataset = sum(r["match_dataset_vs_csv"] for r in rows)
    n_match_fog = sum(r["match_fog_vs_csv"] for r in rows)

    valid_diffs = [r for r in rows if r["shape_note"] == ""]
    diff_maxes = [r["diff_max"] for r in valid_diffs]
    diff_means = [r["diff_mean"] for r in valid_diffs]

    lines = []
    lines.append("# Prueba de sensibilidad de features — dataset vs Fog\n")
    lines.append(f"Checkpoint: `{CHECKPOINT_DIR.name}/best_model.pt` "
                  f"(luz_size={config['luz_size']}, hidden_size={config['hidden_size']}). "
                  f"Comparación contra `results/{RUN_ID}_predictions.csv`.\n")
    lines.append(f"Clips comparados: {len(rows)}/104. Fallas de extracción: {len(failures)}.\n")

    lines.append("## Accuracy y F1 macro de sistema por camino\n")
    lines.append("| Camino | Acc sistema | F1 macro sistema |")
    lines.append("|---|---|---|")
    lines.append(f"| CSV guardado (`pred_sistema` original) | {acc_csv:.4f} | {f1_csv:.4f} |")
    lines.append(f"| Reproducción camino dataset (`.npy` + `_standardize_and_clamp`) | {acc_dataset:.4f} | {f1_dataset:.4f} |")
    lines.append(f"| Camino Fog (`YoloV8PoseAdapter` + `New192FeatureExtractor`) | {acc_fog:.4f} | {f1_fog:.4f} |")
    lines.append("")
    lines.append("La fila \"Reproducción camino dataset\" debe coincidir con la fila \"CSV guardado\" — "
                  "confirma que esta prueba reproduce el mismo cálculo que `evaluate.py` antes de comparar contra Fog.\n")

    lines.append("## Coincidencia de pred_sistema contra el CSV guardado\n")
    lines.append(f"- Reproducción dataset == CSV: {n_match_dataset}/{len(rows)} "
                  f"({n_match_dataset/len(rows):.4f})")
    lines.append(f"- Fog == CSV: {n_match_fog}/{len(rows)} ({n_match_fog/len(rows):.4f})\n")

    if diff_maxes:
        lines.append("## Diferencia de features normalizadas (dataset vs Fog), por clip\n")
        lines.append(f"- max|Δ| — media sobre {len(diff_maxes)} clips: {np.mean(diff_maxes):.4g} "
                      f"(máximo: {np.max(diff_maxes):.4g})")
        lines.append(f"- mean|Δ| — media sobre {len(diff_maxes)} clips: {np.mean(diff_means):.4g} "
                      f"(máximo: {np.max(diff_means):.4g})\n")

    mismatches_fog = [r for r in rows if not r["match_fog_vs_csv"]]
    if mismatches_fog:
        lines.append("## Clips donde Fog difiere de la predicción guardada\n")
        lines.append("| stem | true_label | pred CSV | pred Fog | max|Δ| | mean|Δ| |")
        lines.append("|---|---|---|---|---|---|")
        for r in mismatches_fog:
            lines.append(f"| {r['stem']} | {r['true_label']} | {r['pred_stored_csv']} | "
                          f"{r['pred_fog']} | {r['diff_max']:.4g} | {r['diff_mean']:.4g} |")
        lines.append("")

    if failures:
        lines.append("## Clips que fallaron la extracción\n")
        lines.append("| stem | motivo |")
        lines.append("|---|---|")
        for stem, reason in failures:
            lines.append(f"| {stem} | {reason} |")
        lines.append("")

    lines.append("## Todos los clips (detalle)\n")
    lines.append("| stem | clase | true_label | pred CSV | pred dataset (repro) | pred Fog | max|Δ| | mean|Δ| |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r['stem']} | {r['clase']} | {r['true_label']} | {r['pred_stored_csv']} | "
                      f"{r['pred_dataset_repro']} | {r['pred_fog']} | "
                      f"{r['diff_max']:.4g} | {r['diff_mean']:.4g} |")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
