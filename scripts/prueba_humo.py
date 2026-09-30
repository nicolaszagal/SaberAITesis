"""Prueba de humo del flujo completo: un clip por clase de test_trimmed, hasta el veredicto.

Contra un Fog y un Cloud ya levantados sobre una base de prueba **separada** de la de
la validación, por cada clip: configura un combate (`POST /matches/config`), sube el clip
con las luces de `dataset/labels/luz_annotations.csv` (`POST /matches/{id}/clip`) y
registra el veredicto del árbitro (`POST /revisiones/{id}/veredicto`). Imprime una línea
JSON por clip con las latencias medidas por el cliente y guarda todo en `--salida`.

Convenciones de la prueba (no son reglas del sistema):
    - `t_luz_X_ms` = round(frame de luz X / fps · 1000) con el fps real del clip, solo si
      el frame de la luz en el CSV es > 0 (0 = luz apagada, sin instante). Con
      `--alias-obsoleto` envía `has_luz_A/B` y `t_tocado_ms` (primer instante), como antes de
      V02, para comparar que las sugerencias no cambian.
    - Brazo armado: el anotado en Label Studio (proyecto 5, último backup). Un clip sin
      brazo anotado en ambos tiradores aborta la prueba (no hay valor por defecto).
    - Veredicto: `clase_final` = clase real del clip; `decision` = `mantener` si coincide
      con la sugerida y `cambiar` si no (con clasificación no disponible, `cambiar`).

Uso (Fog en :8001, Cloud y Redis de la base de prueba ya levantados):
    cd backend && .venv/bin/python scripts/prueba_humo.py \\
        --evento <evento_id> --arbitro <arbitro_id> --salida humo.json \\
        [--redis-url redis://localhost:6390/0]

Con `--redis-url` (el mismo Redis de Cloud y Fog) agrega `inferencia_ms`, la latencia del
clasificador publicada por Cloud (F-027, ≤ 50 ms).
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from glob import glob
from pathlib import Path

import cv2
import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"
TRIMMED_TEST = DATASET / "dataset trimmed" / "test_trimmed"
LUZ_CSV = DATASET / "labels" / "luz_annotations.csv"
LABELS_DIR = DATASET / "labels"
LS_PROYECTO_TEST = 5  # Label Studio: proyecto de test (lleva weapon_side_A/B)

# Un clip por clase (el primero por orden alfabético de cada carpeta de test_trimmed).
CLASES = ["AttackA", "AttackB", "ContrattackA", "ContrattackB", "RiposteA", "RiposteB"]


def clip_por_clase(clase: str) -> Path:
    """Devuelve el primer clip (orden alfabético) de la clase en test_trimmed.

    Args:
        clase: nombre de la clase, igual al de la carpeta.

    Returns:
        Ruta del `.mp4`.

    Raises:
        FileNotFoundError: si la carpeta no tiene clips.
    """
    clips = sorted((TRIMMED_TEST / clase).glob("*.mp4"))
    if not clips:
        raise FileNotFoundError(f"Sin clips en {TRIMMED_TEST / clase}")
    return clips[0]


def brazos_anotados() -> dict[str, dict[str, str]]:
    """Lee el brazo armado de cada clip de test del último backup de Label Studio.

    Returns:
        stem -> {"weapon_side_A": "right"|"left", "weapon_side_B": ...} (solo los anotados).
    """
    backup = sorted(glob(str(LABELS_DIR / "label_studio_backup_*.sqlite3")))[-1]
    con = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    lados: dict[str, dict[str, str]] = {}
    filas = con.execute(
        "SELECT t.data, tc.result FROM task t JOIN task_completion tc ON tc.task_id = t.id "
        "WHERE tc.was_cancelled = 0 AND t.project_id = ?",
        (LS_PROYECTO_TEST,),
    )
    for data_s, res_s in filas:
        stem = Path(json.loads(data_s)["filename"]).stem
        for item in json.loads(res_s) if res_s else []:
            nombre, valor = item.get("from_name"), item.get("value", {})
            if nombre in ("weapon_side_A", "weapon_side_B") and valor.get("choices"):
                lados.setdefault(stem, {})[nombre] = valor["choices"][0]
    con.close()
    return lados


def inferencia_ms(redis_url: str, revision_id: str) -> int | None:
    """Lee la latencia del clasificador que Cloud publicó en el stream de la revisión.

    Args:
        redis_url: URL del Redis compartido por Fog y Cloud.
        revision_id: revisión cuyo veredicto se consulta.

    Returns:
        `latencia_inferencia_ms` en ms, o None si el stream no la trae.
    """
    import redis  # dependencia de Fog y Cloud; solo se usa con --redis-url

    entradas = redis.from_url(redis_url, decode_responses=True).xrange(
        f"cloud:verdicts:{revision_id}"
    )
    valor = entradas[0][1].get("latencia_inferencia_ms") if entradas else None
    return round(float(valor)) if valor is not None else None


def correr_clip(
    cliente: httpx.Client, args: argparse.Namespace, clase: str, luces: dict, brazos: dict
) -> dict:
    """Ejecuta configuración, carga del clip y veredicto de un clip.

    Args:
        cliente: cliente HTTP apuntando a Fog.
        args: argumentos de la línea de comandos (evento, árbitro, redis).
        clase: clase real del clip.
        luces: filas de `luz_annotations.csv` por stem.
        brazos: brazo armado anotado por stem (`brazos_anotados`).

    Returns:
        Resultado del clip con las latencias medidas por el cliente.

    Raises:
        SystemExit: si el clip no tiene brazo armado anotado para ambos tiradores.
    """
    mp4 = clip_por_clase(clase)
    stem = mp4.stem
    cap = cv2.VideoCapture(str(mp4))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    luz_a, luz_b = int(luces[stem]["luz_A"]), int(luces[stem]["luz_B"])
    t_luz_a_ms = round(luz_a / fps * 1000) if luz_a > 0 else None
    t_luz_b_ms = round(luz_b / fps * 1000) if luz_b > 0 else None
    t_tocado_ms = min(t for t in (t_luz_a_ms, t_luz_b_ms) if t is not None)
    if args.alias_obsoleto:
        datos_luz = {"t_tocado_ms": t_tocado_ms, "has_luz_A": str(luz_a > 0).lower(),
                     "has_luz_B": str(luz_b > 0).lower()}
    else:
        datos_luz = {k: v for k, v in (("t_luz_a_ms", t_luz_a_ms), ("t_luz_b_ms", t_luz_b_ms))
                     if v is not None}
    lados = brazos.get(stem, {})
    if len(lados) < 2:
        sys.exit(f"{stem}: brazo armado sin anotar; no se analiza sin brazo declarado")

    t0 = time.perf_counter()
    r = cliente.post("/matches/config", json={
        "evento_id": args.evento, "pista": "P-humo", "arbitro_id": args.arbitro,
        "alias_A": "Rojo", "weapon_side_A": lados["weapon_side_A"],
        "alias_B": "Verde", "weapon_side_B": lados["weapon_side_B"],
    })
    r.raise_for_status()
    match_id = r.json()["match_id"]
    t1 = time.perf_counter()
    with mp4.open("rb") as f:
        r = cliente.post(
            f"/matches/{match_id}/clip",
            files={"file": (mp4.name, f, "video/mp4")},
            data=datos_luz,
        )
    t2 = time.perf_counter()
    r.raise_for_status()
    clip = r.json()
    sugerida = clip["action"]
    decision = "mantener" if sugerida == clase else "cambiar"
    r = cliente.post(f"/revisiones/{clip['revision_id']}/veredicto", json={
        "decision": decision, "clase_final": clase, "arbitro_id": args.arbitro})
    t3 = time.perf_counter()
    veredicto = r.json() if r.status_code == 200 else {"error": r.text}
    return {
        "clip": stem, "frames": frames, "fps": round(fps, 2), "luz_A": luz_a, "luz_B": luz_b,
        "t_luz_a_ms": t_luz_a_ms, "t_luz_b_ms": t_luz_b_ms, "t_tocado_ms": t_tocado_ms, "brazos": f"{lados['weapon_side_A']}/{lados['weapon_side_B']}",
        "disponible": clip["disponible"], "motivo": clip["motivo"], "sugerida": sugerida,
        "confianza": clip["confidence"], "clase_final": clase, "decision": decision,
        "veredicto_http": r.status_code, "auditoria_seq": veredicto.get("auditoria_seq"),
        "ms_config": round((t1 - t0) * 1000), "ms_clip": round((t2 - t1) * 1000),
        "ms_veredicto": round((t3 - t2) * 1000), "revision_id": clip["revision_id"],
        "inferencia_ms": (
            inferencia_ms(args.redis_url, clip["revision_id"]) if args.redis_url else None
        ),
    }


def main() -> int:
    """Corre un clip por clase y guarda los resultados.

    Returns:
        0 si todos los veredictos se registraron (HTTP 200); 1 si alguno falló.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evento", required=True, help="evento_id de la base de prueba")
    parser.add_argument("--arbitro", required=True, help="arbitro_id de la base de prueba")
    parser.add_argument("--fog-url", default="http://localhost:8001")
    parser.add_argument("--redis-url", default=None, help="Redis de Cloud, para inferencia_ms")
    parser.add_argument("--salida", type=Path, required=True, help="JSON con los resultados")
    parser.add_argument(
        "--alias-obsoleto", action="store_true",
        help="envía has_luz_A/B y t_tocado_ms (forma anterior a V02) en vez de t_luz_a_ms/t_luz_b_ms",
    )
    args = parser.parse_args()

    luces = {fila["stem"]: fila for fila in csv.DictReader(LUZ_CSV.open(encoding="utf-8"))}
    brazos = brazos_anotados()
    resultados = []
    with httpx.Client(base_url=args.fog_url, timeout=120) as cliente:
        for clase in CLASES:
            resultados.append(correr_clip(cliente, args, clase, luces, brazos))
            print(json.dumps(resultados[-1], ensure_ascii=False), flush=True)
    args.salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if all(r["veredicto_http"] == 200 for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
