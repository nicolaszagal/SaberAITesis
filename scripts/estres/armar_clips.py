"""ESTRES01: fija los 12 clips de test de la prueba de carga en `scripts/estres/clips.json`.

Toma los 10 stems de `scripts/datos/clips_referencia.json` (DEPLOY10, ya con brazo armado anotado) y
completa 12 con el primer clip de test anotado (orden `(clase, stem)`) de RiposteA y de RiposteB que no
esté ya elegido. Decisión del autor (ESTRES01): se usan los **originales** de `dataset raw/test`
(~300 fotogramas) para que Fog aplique la ventana de DEF-32 (76 fotogramas), que es el caso real.
Las luces anotadas (`dataset/labels/luz_annotations.csv`) están en fotogramas del clip trimmed; en el
original se derivan como `round(fi * fps / LS_FPS)` (`fi` de `trim_summary.csv`, igual que
`dataset/06_trim_clips.py`) más el fotograma de luz del trimmed. Es una derivación (SUPUESTO): los
instantes no entran a las features, solo centran la ventana, y se comprueba que caigan dentro del clip.
Reparte los clips en 4 pistas de 3: la pista k recibe los índices
k, k+4 y k+8, para mezclar clases en cada pista. Es la selección del asistente; el autor puede cambiarla.

Uso (desde backend/): .venv/bin/python scripts/estres/armar_clips.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import cv2

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import prueba_humo  # noqa: E402  (reutiliza la lectura de brazos anotados y las rutas del dataset)

SALIDA = Path(__file__).with_name("clips.json")
REFERENCIA = BACKEND_DIR / "scripts" / "datos" / "clips_referencia.json"
LS_FPS = 24  # `LS_FPS` de dataset/06_trim_clips.py (Label Studio indexa a 24 fps)
RAW_TEST = prueba_humo.DATASET / "dataset raw" / "test"
PISTAS = 4
POR_PISTA = 3


def _entrada(stem: str, clase: str, ruta: Path, luces: dict, brazos: dict, inicios: dict) -> dict:
    """Arma la entrada de un clip: ruta, brazos, instantes de luz en ms y sha256.

    Args:
        stem: nombre del clip sin extensión.
        clase: clase real del clip (carpeta del dataset).
        ruta: ruta del `.mp4` original en `dataset raw/test`.
        luces: filas de `luz_annotations.csv` por stem.
        inicios: `fi` (fotograma de Label Studio) de `trim_summary.csv` por stem.
        brazos: brazo armado anotado por stem.

    Returns:
        Diccionario serializable con lo que necesita `carga.py`.

    Raises:
        SystemExit: si falta el brazo armado de algún tirador o el clip no abre.
    """
    lados = brazos.get(stem, {})
    if len(lados) < 2:
        sys.exit(f"{stem}: brazo armado sin anotar")
    cap = cv2.VideoCapture(str(ruta))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if not fps or fps <= 0:
        sys.exit(f"{stem}: no abre o no informa fps")
    duracion_ms = frames / fps * 1000
    luz_a, luz_b = int(luces[stem]["luz_A"]), int(luces[stem]["luz_B"])
    base = round(inicios[stem] * fps / LS_FPS)  # fotograma real del original donde empieza el trimmed
    t_a = round((base + luz_a) / fps * 1000) if luz_a > 0 else None
    t_b = round((base + luz_b) / fps * 1000) if luz_b > 0 else None
    if t_a is None and t_b is None:
        sys.exit(f"{stem}: sin ninguna luz anotada")
    if not 0 <= min(t for t in (t_a, t_b) if t is not None) <= duracion_ms:
        sys.exit(f"{stem}: el instante derivado cae fuera del original")
    return {
        "stem": stem,
        "clase_dataset": clase,
        "ruta": str(ruta.relative_to(prueba_humo.REPO_ROOT)),
        "weapon_side_A": lados["weapon_side_A"],
        "weapon_side_B": lados["weapon_side_B"],
        "t_luz_a_ms": t_a,
        "t_luz_b_ms": t_b,
        "t_tocado_ms": min(t for t in (t_a, t_b) if t is not None),
        "fps": round(float(fps), 2),
        "frames": frames,
        "bytes": ruta.stat().st_size,
        "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
    }


def main() -> None:
    """Genera `clips.json` con 12 clips y su reparto en 4 pistas."""
    brazos = prueba_humo.brazos_anotados()
    with open(prueba_humo.LUZ_CSV, newline="") as f:
        luces = {fila["stem"]: fila for fila in csv.DictReader(f)}
    with open(prueba_humo.LABELS_DIR / "trim_summary.csv", newline="") as f:
        inicios = {fila["stem"]: int(fila["fi"]) for fila in csv.DictReader(f)}
    elegidos = [(c["stem"], c["clase_dataset"]) for c in json.load(open(REFERENCIA))["clips"]]
    for clase in ("RiposteA", "RiposteB"):
        for mp4 in sorted((prueba_humo.TRIMMED_TEST / clase).glob("*.mp4")):
            if mp4.stem in brazos and len(brazos[mp4.stem]) == 2 and mp4.stem not in dict(elegidos):
                elegidos.append((mp4.stem, clase))
                break
    if len(elegidos) != PISTAS * POR_PISTA:
        sys.exit(f"se esperaban {PISTAS * POR_PISTA} clips y hay {len(elegidos)}")
    clips = [
        _entrada(stem, clase, RAW_TEST / clase / f"{stem}.mp4", luces, brazos, inicios)
        for stem, clase in elegidos
    ]
    pistas = {f"P{k + 1}": [clips[k + PISTAS * j]["stem"] for j in range(POR_PISTA)] for k in range(PISTAS)}
    SALIDA.write_text(json.dumps({
        "descripcion": "12 clips fijos de test para ESTRES01 (dataset raw/test); Fog aplica la ventana de DEF-32.",
        "pistas": pistas,
        "clips": clips,
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"escrito {SALIDA}")
    for p, stems in pistas.items():
        print(p, stems)


if __name__ == "__main__":
    main()
