"""Diagnóstico de la discrepancia entre los .npy de entrenamiento y Fog (test set, 104 clips).

Solo lee `dataset/` (clips, .npy, base de Label Studio, estadísticas, checkpoint);
no modifica nada allí ni en código de producción. Reutiliza `05_extract_features.py`
cargándolo como módulo (sin editarlo) para reproducir el camino de entrenamiento.

Etapas (cada una cachea su resultado en --cache-dir y se puede repetir sin recalcular):

  1. Fog sobre los 104 clips de `test_trimmed` (YoloV8PoseAdapter + New192FeatureExtractor),
     con dos variantes de brazo armado: derecha/derecha (como en
     `sensibilidad_features.py`) y el brazo anotado en Label Studio (pk=5).
  2. Distribución de |Δ| normalizada (media y p95 por clip, por grupo de columnas,
     por posición del frame, desplazamiento temporal).
  3. Rango de frames: T del .npy contra los frames del clip trimmed, el rango
     que da Label Studio (pk=2) y la alineación pixel a pixel con el clip original.
  4. Intercambio A/B entre el bloque de Fog y el del .npy.
  5. Para 12 clips que cambian de clase con Fog y 5 que no: camino de
     entrenamiento (`process_clip` de 05_extract_features.py) sobre el clip
     trimmed y sobre el clip original, comparados contra el .npy guardado.

Uso:
    cd backend && .venv/bin/python scripts/diagnostico_discrepancia.py --cache-dir <dir>

Salida:
    backend/docs/evidencia/diagnostico_discrepancia_tablas.md
"""

# ruff: noqa: E402  # imports tras ajustar sys.path (ver sensibilidad_features.py)

from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
import sqlite3
import sys
from glob import glob
from pathlib import Path

import cv2
import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Importar sensibilidad_features ajusta sys.path (backend/ y lstm_6class/) y trae
# las utilidades del camino Fog y del clasificador ya validadas.
import sensibilidad_features as sf
from dataset import CLASSES, _standardize_and_clamp
from fog.domain.models import WeaponSide

REPO_ROOT = sf.REPO_ROOT
DATASET_DIR = sf.DATASET_DIR
BACKEND_DIR = sf.BACKEND_DIR
ORIG_DIR = DATASET_DIR / "dataset raw" / "test"
LABELS_DIR = DATASET_DIR / "labels"
OUT_PATH = BACKEND_DIR / "docs" / "evidencia" / "diagnostico_discrepancia_tablas.md"

# Grupos de columnas dentro del bloque de un tirador (96 columnas). Ver DATA_PIPELINE.md §3.
GROUPS = {
    "posición (0-50)": (0, 51),
    "velocidad (51-84)": (51, 85),
    "paso (85-88)": (85, 89),
    "arma (89-90)": (89, 91),
    "bio (91-95)": (91, 96),
}
LS_FPS = 24  # 05_extract_features.py: Label Studio indexa a 24 fps
N_FIRST = 5
TOL = 1e-4  # tolerancia de la prueba de paridad (test_feature_parity_training_vs_fog.py)


# ─────────────────────────── carga de metadatos ───────────────────────────

def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_ls_meta() -> dict[str, dict]:
    """Lee del último backup de Label Studio: rango original (pk=2) y datos de test (pk=5).

    Returns:
        stem -> {fi_ls, ff_ls (pk=2, unidades 24 fps), ff_trim (pk=5), side_a, side_b}.
    """
    db = sorted(glob(str(LABELS_DIR / "label_studio_backup_*.sqlite3")))[-1]
    con = sqlite3.connect(db)
    cur = con.cursor()
    meta: dict[str, dict] = {}
    for project_id in (2, 5):
        cur.execute(
            "SELECT t.data, tc.result FROM task t JOIN task_completion tc ON tc.task_id = t.id "
            "WHERE tc.was_cancelled = 0 AND t.project_id = ?", (project_id,))
        for data_s, res_s in cur.fetchall():
            data = json.loads(data_s)
            if data.get("split") != "test":
                continue
            stem = Path(data["filename"]).stem
            entry = meta.setdefault(stem, {})
            for item in json.loads(res_s) if res_s else []:
                name, val = item.get("from_name"), item.get("value", {})
                if project_id == 2 and name in ("frame_inicio", "frame_fin"):
                    entry["fi_ls" if name == "frame_inicio" else "ff_ls"] = int(val["number"])
                if project_id == 5 and name in ("weapon_side_A", "weapon_side_B") and val.get("choices"):
                    entry["side_a" if name == "weapon_side_A" else "side_b"] = val["choices"][0]
            if project_id == 5:
                entry["ff_trim"] = int(data.get("frame_fin_trimmed", -1))
    con.close()
    return meta


def sides_of(meta: dict) -> tuple[WeaponSide, WeaponSide]:
    """Brazo armado anotado; 'right' si no está anotado (mismo default que 05_extract_features.py)."""
    return WeaponSide(meta.get("side_a", "right")), WeaponSide(meta.get("side_b", "right"))


# ─────────────────────────── etapa 1: Fog ───────────────────────────

def track_with_fog(adapter, mp4: Path):
    """Detección + tracking de Fog sobre un clip. Devuelve (TrackedSequence, frames decodificados)."""
    session = adapter.start_session()
    cap = cv2.VideoCapture(str(mp4))
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        session.add_frame(frame)
        n += 1
    cap.release()
    return session.finish(), n


def fog_variants(extractor, tracked, meta: dict) -> dict[str, np.ndarray]:
    """Features normalizadas de Fog para ambas variantes de brazo armado."""
    out = {}
    for name, sides in (("fog_right", (WeaponSide.RIGHT, WeaponSide.RIGHT)), ("fog_ann", sides_of(meta))):
        raw, _ = extractor.extract_raw(tracked, *sides)
        out[name] = extractor.normalize(raw.copy())
    return out


# ─────────────────────────── métricas ───────────────────────────

def diff_metrics(ref: np.ndarray, other: np.ndarray) -> dict:
    """Métricas de |ref - other| para dos secuencias (T, 192) con el mismo T."""
    d = np.abs(ref - other)
    out = {"mean": float(d.mean()), "p95": float(np.percentile(d, 95)), "max": float(d.max()),
           "frac_gt_tol": float((d > TOL).mean())}
    for block, off in (("A", 0), ("B", 96)):
        for gname, (lo, hi) in GROUPS.items():
            out[f"{block} {gname}"] = float(d[:, off + lo: off + hi].mean())
    head, tail = d[:N_FIRST], d[N_FIRST:]
    out["first_mean"] = float(head.mean())
    out["first_p95"] = float(np.percentile(head, 95))
    out["rest_mean"] = float(tail.mean()) if tail.size else float("nan")
    out["rest_p95"] = float(np.percentile(tail, 95)) if tail.size else float("nan")
    return out


def best_shift(ref: np.ndarray, other: np.ndarray, max_shift: int = 3) -> tuple[int, dict[int, float]]:
    """Desplazamiento temporal k que minimiza mean|ref[t] - other[t+k]| sobre el solapamiento."""
    scores = {}
    T = len(ref)
    for k in range(-max_shift, max_shift + 1):
        lo, hi = max(0, -k), min(T, len(other) - k)
        if hi - lo >= 3:
            scores[k] = float(np.abs(ref[lo:hi] - other[lo + k: hi + k]).mean())
    return min(scores, key=scores.get), scores


def ab_swap_metrics(fog: np.ndarray, npy: np.ndarray) -> dict:
    """Compara el bloque A/B de Fog contra los bloques del .npy (espacio normalizado)."""
    fa, fb, na, nb = fog[:, :96], fog[:, 96:], npy[:, :96], npy[:, 96:]
    same = np.abs(fa - na).mean(axis=1) + np.abs(fb - nb).mean(axis=1)   # por frame
    swap = np.abs(fa - nb).mean(axis=1) + np.abs(fb - na).mean(axis=1)
    corr = lambda x, y: float(np.corrcoef(x.ravel(), y.ravel())[0, 1])  # noqa: E731
    return {
        "same": float(same.mean()), "swap": float(swap.mean()),
        "swapped": bool(swap.mean() < same.mean()),
        "frames_swap_closer": int((swap < same).sum()), "T": len(fog),
        "corr_AA": corr(fa, na), "corr_AB": corr(fa, nb),
    }


def side_of(cls: str) -> str:
    return cls[-1]


def summarize(values: list[float]) -> str:
    v = np.asarray([x for x in values if not np.isnan(x)])
    return (f"{np.mean(v):.4g} / {np.median(v):.4g} / {np.percentile(v, 95):.4g} / {np.max(v):.4g}"
            if len(v) else "n/d")


# ─────────────────────────── etapa 3: rango de frames ───────────────────────────

def video_info(mp4: Path) -> dict:
    cap = cv2.VideoCapture(str(mp4))
    info = {"count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), "fps": cap.get(cv2.CAP_PROP_FPS)}
    cap.release()
    return info


def load_crops() -> dict[str, tuple[int, int, int, int]]:
    """Recorte espacial (x, y, w, h) por stem, de dataset/labels/crop_coords.csv."""
    import csv
    with open(LABELS_DIR / "crop_coords.csv", newline="", encoding="utf-8") as f:
        return {r["stem"]: (int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])) for r in csv.DictReader(f)}


def read_frames(mp4: Path, lo: int, hi: int, crop=None, size=(64, 36)) -> list[np.ndarray]:
    """Frames [lo, hi] (índices inclusive) en gris, recortados (x, y, w, h) y reescalados a `size`."""
    cap = cv2.VideoCapture(str(mp4))
    frames, n = [], 0
    while n <= hi:
        ok, f = cap.read()
        if not ok:
            break
        if n >= lo:
            if crop:
                x, y, w, h = crop
                f = f[y:y + h, x:x + w]
            frames.append(cv2.cvtColor(cv2.resize(f, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32))
        n += 1
    cap.release()
    return frames


def alignment_with_original(trim: Path, orig: Path, fi_real: int, n_trim: int, crop) -> dict | None:
    """Desfase entre el clip trimmed y el original: k que minimiza la diferencia de píxeles.

    Returns:
        None si el clip trimmed tiene otra resolución que el original y no hay recorte conocido.
    """
    tcap, ocap = cv2.VideoCapture(str(trim)), cv2.VideoCapture(str(orig))
    tsize = (int(tcap.get(3)), int(tcap.get(4)))
    osize = (int(ocap.get(3)), int(ocap.get(4)))
    tcap.release(); ocap.release()
    if crop is None and tsize != osize:
        return None
    if crop is not None and tsize != (crop[2], crop[3]):
        crop = None
        if tsize != osize:
            return None
    t_frames = read_frames(trim, 0, n_trim - 1)
    o_frames = read_frames(orig, max(0, fi_real - 3), fi_real + n_trim + 2, crop=crop)
    base = fi_real - max(0, fi_real - 3)
    scores = {}
    for k in range(-3, 4):
        diffs = []
        for i, tf in enumerate(t_frames):
            j = base + i + k
            if 0 <= j < len(o_frames):
                diffs.append(float(np.abs(tf - o_frames[j]).mean()))
        if diffs:
            scores[k] = float(np.mean(diffs))
    best = min(scores, key=scores.get)
    return {"best_k": best, "diff_at_0": scores.get(0, float("nan")), "diff_best": scores[best]}


# ─────────────────────────── etapa 5: camino de entrenamiento ───────────────────────────

def train_path(ef, yolo_cls, pose_model: Path, mp4: Path, ann: dict, is_trimmed: bool):
    """`process_clip` de 05_extract_features.py con instancia YOLO nueva por clip.

    Returns:
        (secuencia cruda (T, 192) o None, stats).
    """
    model = yolo_cls(str(pose_model))
    return ef.process_clip(str(mp4), ann, model, 3, is_trimmed=is_trimmed)


# ─────────────────────────── main ───────────────────────────

def cached(path: Path, fn):
    if path.exists():
        return pickle.loads(path.read_bytes())
    value = fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(value))
    return value


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("--skip-original", action="store_true", help="omite la etapa 5 sobre clips originales")
    args = ap.parse_args()
    cache = args.cache_dir

    from ultralytics import YOLO

    from fog.infrastructure.features.new192_feature_extractor import New192FeatureExtractor
    from fog.infrastructure.features.preprocessing_profile import load_profile
    from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter

    stats = np.load(sf.STATS_PATH)
    mean, std = stats["mean"].astype(np.float32), stats["std"].astype(np.float32)
    adapter = YoloV8PoseAdapter(YOLO(str(sf.POSE_MODEL_PATH)))
    extractor = New192FeatureExtractor(mean=stats["mean"], std=stats["std"], profile=load_profile("lstm_6class"))
    with open(sf.CHECKPOINT_DIR / "run_config.json") as f:
        config = json.load(f)
    model = sf.build_model(config)
    luz_map = sf.load_luz_map()
    stored = sf.load_stored_predictions()
    meta = load_ls_meta()
    clips = sf.discover_clips()
    ef = load_module("extract_features_train", DATASET_DIR / "05_extract_features.py")

    # ── Etapa 1: Fog sobre los 104 clips ──
    rows: dict[str, dict] = {}
    for i, (cls, stem, npy_path, mp4) in enumerate(clips, 1):
        print(f"[fog {i}/{len(clips)}] {stem}", flush=True)
        tracked, n_dec = cached(cache / "tracked" / f"{stem}.pkl", lambda m=mp4: track_with_fog(adapter, m))
        norm_npy = _standardize_and_clamp(np.load(npy_path).astype(np.float32), mean, std)
        fog = fog_variants(extractor, tracked, meta[stem])
        luz = luz_map.get(stem, (False, False))
        rows[stem] = {
            "cls": cls, "true": stored[stem]["true_label"], "csv": stored[stem]["pred_sistema"],
            "T_npy": len(norm_npy), "n_dec": n_dec, "lock_frame": tracked.lock_frame,
            "npy": norm_npy, "fog": fog, "mp4": mp4, "npy_path": npy_path,
            "pred_npy": sf.classify(model, norm_npy, luz),
            "pred": {k: sf.classify(model, v, luz) for k, v in fog.items() if len(v) > 0},
        }

    # ── Etapas 2 y 4: distribución de diferencias y A/B ──
    for stem, r in rows.items():
        r["metrics"], r["shift"], r["ab"] = {}, {}, {}
        for variant, fog in r["fog"].items():
            if len(fog) == len(r["npy"]):
                r["metrics"][variant] = diff_metrics(r["npy"], fog)
                r["shift"][variant] = best_shift(r["npy"], fog)
                r["ab"][variant] = ab_swap_metrics(fog, r["npy"])

    # ── Etapa 3: rango de frames ──
    crops = load_crops()
    for stem, r in rows.items():
        m = meta[stem]
        info = video_info(r["mp4"])
        orig = ORIG_DIR / r["cls"] / f"{stem}.mp4"
        oinfo = video_info(orig) if orig.exists() else {"count": -1, "fps": float("nan")}
        fps = oinfo["fps"] if oinfo["fps"] == oinfo["fps"] else 30.0
        fi_real = max(0, round(m["fi_ls"] * fps / LS_FPS))
        ff_real = min(oinfo["count"] - 1, round(m["ff_ls"] * fps / LS_FPS))
        r["range"] = {
            "trim_count": info["count"], "orig_count": oinfo["count"], "orig_fps": oinfo["fps"],
            "fi_real": fi_real, "ff_real": ff_real, "T_expected_pk2": ff_real - fi_real + 1,
            # camino de 05_extract_features.py si el clip trimmed no se hubiera encontrado (pk=5: fi=0, ff=frame_fin_trimmed)
            "T_if_original_pk5": min(oinfo["count"] - 1, round(m["ff_trim"] * fps / LS_FPS)) + 1,
            "T_ff_trim_plus1": m["ff_trim"] + 1,
        }
        r["align"] = (alignment_with_original(r["mp4"], orig, fi_real, r["T_npy"], crops.get(stem))
                      if orig.exists() else None)

    # ── Etapa 5: 12 clips que cambian y 5 que no ──
    changed = sorted(s for s, r in rows.items() if r["pred"]["fog_right"] != r["csv"])
    unchanged = sorted(s for s, r in rows.items() if r["pred"]["fog_right"] == r["csv"])
    picks = [unchanged[int(i)] for i in np.linspace(0, len(unchanged) - 1, 5)]
    subset = changed + picks
    train_rows: dict[str, dict] = {}
    for i, stem in enumerate(subset, 1):
        r, m = rows[stem], meta[stem]
        sa, sb = sides_of(m)
        ann_trim = {"frame_inicio": 0, "frame_fin": 0, "luz_A": 0, "luz_B": 0,
                    "weapon_side_A": sa.value, "weapon_side_B": sb.value}
        ann_orig = {**ann_trim, "frame_inicio": m["fi_ls"], "frame_fin": m["ff_ls"]}
        print(f"[train {i}/{len(subset)}] {stem}", flush=True)
        entry = {"group": "cambia" if stem in changed else "no cambia"}
        variants = [("trim", r["mp4"], ann_trim, True)]
        orig = ORIG_DIR / r["cls"] / f"{stem}.mp4"
        if not args.skip_original and orig.exists():
            variants.append(("orig", orig, ann_orig, False))
        for name, mp4, ann, is_trim in variants:
            seq, st = cached(cache / "train" / f"{stem}_{name}.pkl",
                             lambda mp4=mp4, ann=ann, is_trim=is_trim: train_path(ef, YOLO, sf.POSE_MODEL_PATH, mp4, ann, is_trim))
            if seq is None:
                entry[name] = {"error": st.get("error")}
                continue
            norm = _standardize_and_clamp(seq.astype(np.float32).copy(), mean, std)
            luz = luz_map.get(stem, (False, False))
            e = {"shape": tuple(norm.shape), "lock_frame": st.get("lock_frame"), "pred": sf.classify(model, norm, luz)}
            if len(norm) == len(r["npy"]):
                e["vs_npy"] = diff_metrics(r["npy"], norm)
                e["ab_vs_npy"] = ab_swap_metrics(norm, r["npy"])
                e["shift_vs_npy"] = best_shift(r["npy"], norm)
                fog = r["fog"]["fog_ann"]
                if len(fog) == len(norm):
                    e["vs_fog_ann"] = diff_metrics(fog, norm)
            entry[name] = e
        train_rows[stem] = entry

    write_tables(rows, train_rows, changed, picks, config)
    print(f"\nOK {OUT_PATH}")


# ─────────────────────────── reporte ───────────────────────────

def write_tables(rows, train_rows, changed, picks, config) -> None:
    L: list[str] = []
    stems = sorted(rows)
    L.append("# Diagnóstico de discrepancia: tablas generadas\n")
    L.append("Generado por `scripts/diagnostico_discrepancia.py`. Interpretación en `diagnostico_discrepancia.md`.\n")
    L.append(f"Clips: {len(stems)}. Checkpoint `{sf.CHECKPOINT_DIR.name}/best_model.pt`. "
             f"Espacio de comparación: features normalizadas (estandarizadas y recortadas), como en `sensibilidad_features.md`.\n")

    # exactitud por variante
    L.append("## 0. Accuracy / F1 macro de sistema según brazo armado de Fog\n")
    L.append("| Camino | Acc | F1 macro | Coincide con CSV |")
    L.append("|---|---|---|---|")
    labels = [CLASSES.index(rows[s]["true"]) for s in stems]
    for name, get in (("CSV guardado", lambda r: r["csv"]), (".npy reproducido", lambda r: r["pred_npy"]),
                      ("Fog derecha/derecha", lambda r: r["pred"]["fog_right"]),
                      ("Fog brazo anotado (pk=5)", lambda r: r["pred"]["fog_ann"])):
        preds = [CLASSES.index(get(rows[s])) for s in stems]
        acc, f1, _ = sf.compute_per_class_metrics(preds, labels)
        agree = sum(get(rows[s]) == rows[s]["csv"] for s in stems)
        L.append(f"| {name} | {acc:.4f} | {f1:.4f} | {agree}/{len(stems)} |")
    n_left = sum(1 for s in stems if "left" in (meta_sides(s)))
    L.append("")
    L.append(f"Clips con al menos un brazo anotado 'left': {n_left}/{len(stems)}.\n")

    # etapa 2
    for variant, title in (("fog_right", "Fog derecha/derecha (igual que `sensibilidad_features.md`)"),
                           ("fog_ann", "Fog con brazo armado anotado (pk=5)")):
        ms = [rows[s]["metrics"][variant] for s in stems if variant in rows[s]["metrics"]]
        L.append(f"## 1. Distribución de |Δ| normalizada — {title}\n")
        L.append(f"Clips con el mismo T: {len(ms)}/{len(stems)}. Cada celda: media / mediana / p95 / máx **entre clips** del valor por clip.\n")
        L.append("| Métrica por clip | media / mediana / p95 / máx |")
        L.append("|---|---|")
        for key, label in (("mean", "media de |Δ|"), ("p95", "p95 de |Δ|"), ("max", "máx de |Δ|"),
                           ("frac_gt_tol", f"fracción de valores con |Δ| > {TOL:g}")):
            L.append(f"| {label} | {summarize([m[key] for m in ms])} |")
        L.append("")
        L.append("Por grupo de columnas (media de |Δ| dentro del grupo, por clip):\n")
        L.append("| Grupo | Tirador A | Tirador B |")
        L.append("|---|---|---|")
        for g in GROUPS:
            L.append(f"| {g} | {summarize([m['A ' + g] for m in ms])} | {summarize([m['B ' + g] for m in ms])} |")
        L.append("")
        L.append(f"Por posición del frame (primeros {N_FIRST} vs el resto):\n")
        L.append("| Tramo | media de |Δ| | p95 de |Δ| |")
        L.append("|---|---|---|")
        L.append(f"| primeros {N_FIRST} | {summarize([m['first_mean'] for m in ms])} | {summarize([m['first_p95'] for m in ms])} |")
        L.append(f"| resto | {summarize([m['rest_mean'] for m in ms])} | {summarize([m['rest_p95'] for m in ms])} |")
        L.append("")
        ks = [rows[s]["shift"][variant][0] for s in stems if variant in rows[s]["shift"]]
        L.append("Desplazamiento temporal que minimiza |Δ| (k=0 es alineación frame a frame): "
                 + ", ".join(f"k={k}: {ks.count(k)}" for k in sorted(set(ks))) + "\n")

    # etapa 3
    L.append("## 2. Rango de frames\n")
    same_T = sum(1 for s in stems if rows[s]["T_npy"] == rows[s]["range"]["trim_count"])
    same_dec = sum(1 for s in stems if rows[s]["T_npy"] == rows[s]["n_dec"])
    same_pk2 = sum(1 for s in stems if rows[s]["T_npy"] == rows[s]["range"]["T_expected_pk2"])
    same_ff = sum(1 for s in stems if rows[s]["T_npy"] == rows[s]["range"]["T_ff_trim_plus1"])
    same_pk5o = sum(1 for s in stems if rows[s]["T_npy"] == rows[s]["range"]["T_if_original_pk5"])
    L.append("| Comparación | Clips con T(.npy) igual |")
    L.append("|---|---|")
    L.append(f"| frames del clip `test_trimmed` (CAP_PROP_FRAME_COUNT) | {same_T}/{len(stems)} |")
    L.append(f"| frames del clip `test_trimmed` realmente decodificados | {same_dec}/{len(stems)} |")
    L.append(f"| rango original pk=2: round(ff·fps/24) − round(fi·fps/24) + 1 | {same_pk2}/{len(stems)} |")
    L.append(f"| pk=5 `frame_fin_trimmed` + 1 | {same_ff}/{len(stems)} |")
    L.append(f"| camino \"original\" con datos de pk=5 (fi=0, ff=round(frame_fin_trimmed·fps/24)) | {same_pk5o}/{len(stems)} |")
    L.append("")
    al = [rows[s]["align"] for s in stems if rows[s]["align"]]
    if al:
        ks = [a["best_k"] for a in al]
        L.append("Alineación píxel a píxel del clip `test_trimmed` contra el original en [fi_real, ff_real]: "
                 + ", ".join(f"k={k}: {ks.count(k)}" for k in sorted(set(ks)))
                 + f" clips. Diferencia media de píxeles (0-255, gris 1/4 res.) en k=0: {summarize([a['diff_at_0'] for a in al])}"
                 " (media / mediana / p95 / máx).\n")
    L.append("| stem | T .npy | frames trimmed | T pk=2 | T pk=5+1 | fps orig | k alineación | lock_frame Fog |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in stems:
        r, rg = rows[s], rows[s]["range"]
        L.append(f"| {s} | {r['T_npy']} | {rg['trim_count']} | {rg['T_expected_pk2']} | {rg['T_ff_trim_plus1']} | "
                 f"{rg['orig_fps']:.2f} | {r['align']['best_k'] if r['align'] else 'n/d'} | {r['lock_frame']} |")
    L.append("")

    # etapa 4
    L.append("## 3. Intercambio A/B (Fog con brazo anotado)\n")
    for variant in ("fog_right", "fog_ann"):
        swapped = [s for s in stems if variant in rows[s]["ab"] and rows[s]["ab"][variant]["swapped"]]
        L.append(f"- `{variant}`: clips con A/B intercambiados (distancia con bloques cruzados < distancia con bloques directos): "
                 f"{len(swapped)}/{len(stems)}" + (f" — {', '.join(swapped)}" if swapped else ""))
    L.append("")
    L.append("| stem | grupo | d directa | d cruzada | frames con cruce más cercano | corr A-A | corr A-B | intercambiado | pred CSV | pred Fog | lado cambia |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in changed + [p for p in picks]:
        r = rows[s]
        ab = r["ab"].get("fog_right")
        if not ab:
            continue
        pf = r["pred"]["fog_right"]
        L.append(f"| {s} | {'cambia' if s in changed else 'no cambia'} | {ab['same']:.3f} | {ab['swap']:.3f} | "
                 f"{ab['frames_swap_closer']}/{ab['T']} | {ab['corr_AA']:.3f} | {ab['corr_AB']:.3f} | "
                 f"{'sí' if ab['swapped'] else 'no'} | {r['csv']} | {pf} | {'sí' if side_of(pf) != side_of(r['csv']) else 'no'} |")
    L.append("")

    # etapa 5
    L.append("## 4. Camino de entrenamiento (`process_clip`, instancia YOLO nueva por clip) vs .npy\n")
    L.append("`trim`: sobre el clip de `test_trimmed` (is_trimmed=True). `orig`: sobre el clip original desde el frame 0, recorte a "
             "[fi, ff] de pk=2 (is_trimmed=False). Brazo armado anotado. |Δ| en espacio normalizado.\n")
    L.append("| stem | grupo | T .npy | trim: T | trim: mean|Δ| vs .npy | trim: max|Δ| vs .npy | trim vs Fog(ann): max|Δ| | "
             "orig: T | orig: lock | orig: mean|Δ| vs .npy | orig: max|Δ| vs .npy | pred CSV | pred trim | pred orig |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    fmt = lambda v: "n/d" if v is None else f"{v:.4g}"  # noqa: E731
    for s in changed + picks:
        e = train_rows[s]
        t, o = e.get("trim", {}), e.get("orig", {})
        L.append(f"| {s} | {e['group']} | {rows[s]['T_npy']} | {t.get('shape', ('n/d',))[0]} | "
                 f"{fmt(t.get('vs_npy', {}).get('mean'))} | {fmt(t.get('vs_npy', {}).get('max'))} | "
                 f"{fmt(t.get('vs_fog_ann', {}).get('max'))} | {o.get('shape', ('n/d',))[0]} | {o.get('lock_frame', 'n/d')} | "
                 f"{fmt(o.get('vs_npy', {}).get('mean'))} | {fmt(o.get('vs_npy', {}).get('max'))} | "
                 f"{rows[s]['csv']} | {t.get('pred', 'n/d')} | {o.get('pred', 'n/d')} |")
    L.append("")
    for name in ("trim", "orig"):
        ms = [train_rows[s][name]["vs_npy"] for s in train_rows if "vs_npy" in train_rows[s].get(name, {})]
        if ms:
            L.append(f"- `{name}` vs .npy ({len(ms)} clips con igual T): mean|Δ| {summarize([m['mean'] for m in ms])}; "
                     f"max|Δ| {summarize([m['max'] for m in ms])} (media / mediana / p95 / máx entre clips).")
    ms = [train_rows[s]["trim"]["vs_fog_ann"] for s in train_rows if "vs_fog_ann" in train_rows[s].get("trim", {})]
    if ms:
        L.append(f"- `trim` vs Fog(ann) ({len(ms)} clips): mean|Δ| {summarize([m['mean'] for m in ms])}; max|Δ| {summarize([m['max'] for m in ms])}.")
    L.append("")

    L.append("## 5. Detalle por clip (Fog con brazo anotado vs .npy)\n")
    L.append("| stem | brazos A/B | mean|Δ| | p95|Δ| | max|Δ| | primeros 5 mean | resto mean | pred CSV | pred Fog(right) | pred Fog(ann) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for s in stems:
        r = rows[s]
        m = r["metrics"].get("fog_ann")
        if not m:
            continue
        sa, sb = meta_sides(s)
        L.append(f"| {s} | {sa}/{sb} | {m['mean']:.4g} | {m['p95']:.4g} | {m['max']:.4g} | {m['first_mean']:.4g} | "
                 f"{m['rest_mean']:.4g} | {r['csv']} | {r['pred']['fog_right']} | {r['pred']['fog_ann']} |")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(L) + "\n", encoding="utf-8")


_META: dict[str, dict] = {}


def meta_sides(stem: str) -> tuple[str, str]:
    if not _META:
        _META.update(load_ls_meta())
    m = _META[stem]
    return m.get("side_a", "right"), m.get("side_b", "right")


if __name__ == "__main__":
    main()
