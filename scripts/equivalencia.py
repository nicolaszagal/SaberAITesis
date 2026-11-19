"""Prueba de equivalencia de Fog entre equipos (DEPLOY10): mismas features, misma clase.

Corre los clips de `scripts/datos/clips_referencia.json` por el mismo camino que Fog en producción
(YoloV8PoseAdapter con `FOG_DEVICE` + New192FeatureExtractor del perfil `lstm_6class`, construidos con
las funciones de `fog.composition`) y por el clasificador de Cloud (LSTM6ClassAdapter, que aplica el
filtro Favero), y compara con `scripts/datos/referencia_salidas.json`.

Modos:
    probar               compara con la referencia y escribe datos/evidencia/equivalencia_<equipo>_<fecha>.json
    generar-referencia   escribe referencia_salidas.json (se hace UNA vez en el Mac con cpu; no pisa una existente)
    medir                corre N veces (por defecto 2) y reporta la diferencia máxima entre corridas, para
                         proponer la cota; no escribe nada

Variables: MODEL_RUN_ID, DATASET_DIR (por defecto ../dataset), FOG_DEVICE (cpu), CLIPS_REFERENCIA_DIR
(opcional: carpeta con <stem>.mp4; si falta, se usa DATASET_DIR/<ruta_dataset>), DATOS_DIR (./datos).

Uso (desde backend/ con el .venv): .venv/bin/python scripts/equivalencia.py probar
"""

# ruff: noqa: E402  # imports tras ajustar sys.path

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from importlib import metadata
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import instalador

DATOS_REFERENCIA = BACKEND_DIR / "scripts" / "datos"
CLIPS_JSON = DATOS_REFERENCIA / "clips_referencia.json"
REFERENCIA_JSON = DATOS_REFERENCIA / "referencia_salidas.json"
RUN_ID_POR_DEFECTO = "20260928_141021"
PERFIL = "lstm_6class"
DECIMALES = 4
PAQUETES_RELEVANTES = ("torch", "torchvision", "ultralytics", "numpy", "opencv-python", "lap", "scipy")


def nombre_equipo() -> str:
    """Nombre corto del equipo, apto para un nombre de archivo.

    Returns:
        Nombre de host sin dominio y solo con letras, números, `-` y `_`.
    """
    crudo = socket.gethostname().split(".")[0]
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in crudo) or "equipo"


def commit_actual() -> str:
    """Commit (HEAD) del código que corre la prueba.

    Returns:
        SHA completo, o `desconocido` fuera de un repositorio git.
    """
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND_DIR, capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"


def versiones() -> dict[str, str]:
    """Versiones instaladas de los paquetes que pueden cambiar las features.

    Returns:
        Paquete -> versión (`no instalado` si falta).
    """
    out = {}
    for paquete in PAQUETES_RELEVANTES:
        try:
            out[paquete] = metadata.version(paquete)
        except metadata.PackageNotFoundError:
            out[paquete] = "no instalado"
    return out


def hash_keypoints(tracked) -> str:
    """SHA-256 de los keypoints y confianzas de ambos tiradores en todos los frames.

    Args:
        tracked: `TrackedSequence` de Fog.

    Returns:
        Hash hexadecimal; cambia si cambia cualquier keypoint (informativo, no decide la aprobación).
    """
    digest = hashlib.sha256()
    for frame in tracked.frames:
        for persona in (frame.person_a, frame.person_b):
            digest.update(bytes([int(persona.detected)]))
            digest.update(persona.keypoints_xy.tobytes())
            digest.update(persona.keypoints_conf.tobytes())
    return digest.hexdigest()


def construir_pipeline(dataset_dir: Path, run_id: str, dispositivo: str):
    """Arma el extractor de Fog y el clasificador de Cloud con los mismos constructores de producción.

    Args:
        dataset_dir: carpeta con yolov8x-pose.pt y lstm_6class/.
        run_id: corrida del modelo (carpeta de checkpoints).
        dispositivo: `FOG_DEVICE` para YOLO.

    Returns:
        (adaptador de pose, extractor de features, clasificador).
    """
    import torch

    from cloud.infrastructure.classifier.lstm6class_adapter import LSTM6ClassAdapter
    from fog.composition import _build_feature_extractor, _load_yolo_model
    from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter
    from shared import config

    config.validar_dispositivo(dispositivo)
    modelo = _load_yolo_model(str(dataset_dir / "yolov8x-pose.pt"))
    adaptador = YoloV8PoseAdapter(modelo, device=dispositivo)
    extractor = _build_feature_extractor(
        str(dataset_dir / "lstm_6class" / "feature_stats.npz"), PERFIL, config.FEATURE_PREPROCESSING_PROFILES_PATH
    )
    clasificador = LSTM6ClassAdapter(
        str(dataset_dir / "lstm_6class" / "checkpoints" / run_id), torch.device("cpu")
    )
    return adaptador, extractor, clasificador


def procesar_clip(adaptador, extractor, clasificador, clip: dict, ruta: Path) -> dict:
    """Corre un clip de referencia por pose, features y clasificación.

    Args:
        adaptador: `YoloV8PoseAdapter`.
        extractor: `New192FeatureExtractor`.
        clasificador: `LSTM6ClassAdapter`.
        clip: entrada de clips_referencia.json (brazo armado y luz anotados).
        ruta: archivo `.mp4`.

    Returns:
        {clase, probabilidades (4 decimales), keypoints_sha256} o {error}.
    """
    import cv2

    from cloud.domain.models import LuzSignal
    from fog.domain.models import WeaponSide

    sesion = adaptador.start_session()
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        return {"error": "no se pudo abrir el video"}
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            sesion.add_frame(frame)
    finally:
        cap.release()
    tracked = sesion.finish()
    salida = extractor.extract(tracked, WeaponSide(clip["brazo_a"]), WeaponSide(clip["brazo_b"]))
    if salida.sequence is None:
        return {"error": salida.stats.get("error", "error desconocido")}
    veredicto = clasificador.classify(salida.sequence, LuzSignal(clip["luz_a"], clip["luz_b"]))
    return {
        "clase": veredicto.action_class.value,
        "probabilidades": {c: round(float(p), DECIMALES) for c, p in veredicto.probs.items()},
        "keypoints_sha256": hash_keypoints(tracked),
    }


def correr(dispositivo: str, dataset_dir: Path, run_id: str) -> dict[str, dict]:
    """Procesa los diez clips de referencia.

    Args:
        dispositivo: `FOG_DEVICE`.
        dataset_dir: raíz del dataset o paquete de modelo.
        run_id: corrida del modelo.

    Returns:
        stem -> salida de `procesar_clip`.
    """
    clips = json.loads(CLIPS_JSON.read_text(encoding="utf-8"))["clips"]
    extra = Path(os.environ["CLIPS_REFERENCIA_DIR"]) if os.environ.get("CLIPS_REFERENCIA_DIR") else None
    adaptador, extractor, clasificador = construir_pipeline(dataset_dir, run_id, dispositivo)
    salidas = {}
    for i, clip in enumerate(clips, start=1):
        print(f"[{i}/{len(clips)}] {clip['stem']}", flush=True)
        try:
            ruta = instalador.ruta_de_clip(clip, dataset_dir, extra)
            salidas[clip["stem"]] = procesar_clip(adaptador, extractor, clasificador, clip, ruta)
        except (FileNotFoundError, ValueError) as exc:
            salidas[clip["stem"]] = {"error": str(exc)}
    return salidas


def diferencia_entre_corridas(a: dict[str, dict], b: dict[str, dict]) -> float:
    """Diferencia máxima de probabilidad entre dos corridas completas.

    Args:
        a: salidas de la primera corrida.
        b: salidas de la segunda.

    Returns:
        Máximo de |p_a - p_b| sobre clips y clases.
    """
    return max(
        abs(a[s]["probabilidades"][c] - b[s]["probabilidades"][c]) for s in a for c in a[s]["probabilidades"]
    )


def _contexto(dispositivo: str, run_id: str) -> dict:
    return {
        "equipo": nombre_equipo(),
        "fecha": instalador.ahora_utc(),
        "commit": commit_actual(),
        "dispositivo": dispositivo,
        "modelo_run_id": run_id,
        "sistema": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "versiones": versiones(),
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada.

    Args:
        argv: argumentos; por defecto `sys.argv[1:]`.

    Returns:
        0 si el modo terminó bien (y, en `probar`, aprobó); 1 en caso contrario.
    """
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("modo", choices=["probar", "generar-referencia", "medir"])
    p.add_argument("--corridas", type=int, default=2, help="solo `medir`")
    p.add_argument("--forzar", action="store_true", help="`generar-referencia`: reemplaza la referencia existente")
    args = p.parse_args(argv)

    dispositivo = os.environ.get("FOG_DEVICE", "cpu")
    run_id = os.environ.get("MODEL_RUN_ID", RUN_ID_POR_DEFECTO)
    dataset_dir = Path(os.environ.get("DATASET_DIR", BACKEND_DIR.parent / "dataset")).resolve()
    datos = Path(os.environ.get("DATOS_DIR", BACKEND_DIR / "datos")).resolve()

    if args.modo == "generar-referencia":
        if REFERENCIA_JSON.exists() and not args.forzar:
            print(f"{REFERENCIA_JSON.name} ya existe: la referencia se genera una sola vez (--forzar la reemplaza).",
                  file=sys.stderr)
            return 1
        if dispositivo != "cpu":
            print("La referencia se genera con FOG_DEVICE=cpu.", file=sys.stderr)
            return 1
        salidas = correr(dispositivo, dataset_dir, run_id)
        if any("error" in s for s in salidas.values()):
            print("Hay clips con error; no se escribe la referencia.", file=sys.stderr)
            return 1
        anterior = {}
        if REFERENCIA_JSON.exists():
            anterior = json.loads(REFERENCIA_JSON.read_text(encoding="utf-8"))
        REFERENCIA_JSON.write_text(json.dumps({
            **_contexto(dispositivo, run_id),
            "decimales": DECIMALES,
            "cota_probabilidad": anterior.get("cota_probabilidad"),
            "clips": salidas,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Referencia escrita en {REFERENCIA_JSON}")
        return 0

    if args.modo == "medir":
        corridas = [correr(dispositivo, dataset_dir, run_id) for _ in range(args.corridas)]
        if any("error" in s for c in corridas for s in c.values()):
            print("Hay clips con error.", file=sys.stderr)
            return 1
        difs = [diferencia_entre_corridas(corridas[i], corridas[i + 1]) for i in range(len(corridas) - 1)]
        mismos_kp = all(
            corridas[0][s]["keypoints_sha256"] == c[s]["keypoints_sha256"] for c in corridas[1:] for s in corridas[0]
        )
        mismas_clases = all(corridas[0][s]["clase"] == c[s]["clase"] for c in corridas[1:] for s in corridas[0])
        print(json.dumps({"corridas": len(corridas), "diferencias_maximas": difs, "keypoints_identicos": mismos_kp,
                          "clases_identicas": mismas_clases}, indent=2))
        return 0

    # probar
    if not REFERENCIA_JSON.exists():
        print("Falta scripts/datos/referencia_salidas.json (se genera una vez en el Mac con cpu).", file=sys.stderr)
        return 1
    referencia = json.loads(REFERENCIA_JSON.read_text(encoding="utf-8"))
    salidas = correr(dispositivo, dataset_dir, run_id)
    resultado = instalador.comparar_salidas(referencia["clips"], salidas, referencia.get("cota_probabilidad"))
    reporte = {**_contexto(dispositivo, run_id), "cota_probabilidad": referencia.get("cota_probabilidad"),
               "referencia": {"equipo": referencia.get("equipo"), "commit": referencia.get("commit"),
                              "dispositivo": referencia.get("dispositivo"), "versiones": referencia.get("versiones")},
               **resultado, "salidas": salidas}
    evidencia = datos / "evidencia"
    evidencia.mkdir(parents=True, exist_ok=True)
    destino = evidencia / f"equivalencia_{reporte['equipo']}_{reporte['fecha'].replace(':', '').replace('-', '')}.json"
    destino.write_text(json.dumps(reporte, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Clase igual en {resultado['clases_iguales']}/{resultado['total']}; "
          f"diferencia máxima {resultado['diferencia_maxima']}; keypoints idénticos {resultado['keypoints_iguales']}/{resultado['total']}")
    print(f"{'APROBADA' if resultado['aprobado'] else 'NO APROBADA'}: {resultado['motivo']}")
    print(f"Reporte: {destino}")
    return 0 if resultado["aprobado"] else 1


if __name__ == "__main__":
    sys.exit(main())
