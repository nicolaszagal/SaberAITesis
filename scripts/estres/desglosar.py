"""ESTRES01: une los resultados de `carga.py` con los logs de tiempo de Fog y la base, y resume por escenario.

Entradas (de una corrida de `carga.py`):
    --jsonl     resultados por solicitud (uno o varios, separados por coma).
    --fog-log   log de Fog con `ESTRES_TIEMPOS=1` (líneas `ESTRES_TIEMPOS etapa=...`).
    --recursos  CSV de recursos del medidor (opcional, uno o varios).
    --psql      comando para consultar la base de la prueba (por defecto, el contenedor `sabre-postgres-1`).

Etapas por solicitud (segundos):
    subida          cliente: hasta enviar el cuerpo completo.
    cola_executor   espera de un hilo del `ThreadPoolExecutor(max_workers=2)` de Fog antes de leer el clip y
                    antes de `finish()` (que no calcula nada pero hace cola en el mismo executor).
    cola_yolo       suma de las esperas del `threading.Lock` de `model.predict()` (YoloV8PoseAdapter).
    pose            `predict` de YOLO + tracking BoT-SORT + decodificación del clip (lo que queda de la lectura).
    features        espera del executor + extracción de features + publicación en Redis.
    cloud_espera    desde publicar en Redis hasta recibir el veredicto, menos la clasificación.
    clasificacion   `latencia_inferencia_ms` que informa Cloud (BiLSTM).
    resto           total menos lo anterior (recorte, guardado, base, respuesta HTTP).

Uso: .venv/bin/python scripts/estres/desglosar.py --jsonl A.jsonl --fog-log fog.log --salida resumen.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from carga import percentil  # misma función que usa la medición

PATRON = re.compile(r"ESTRES_TIEMPOS etapa=(\w+) (.*)$")


def leer_log(ruta: Path, desde: int = 0) -> dict[str, dict]:
    """Lee las líneas `ESTRES_TIEMPOS` de Fog y las agrupa por archivo y por revisión.

    Args:
        ruta: log de Fog.
        desde: byte desde el que leer (para ignorar corridas anteriores).

    Returns:
        `{"clip": {archivo: campos}, "features": {revision: campos}, "espera_cloud": {revision: campos}}`.
    """
    salida: dict[str, dict] = {"clip": {}, "features": {}, "espera_cloud": {}}
    with open(ruta, "rb") as f:
        f.seek(desde)
        for linea in f.read().decode(errors="replace").splitlines():
            m = PATRON.search(linea)
            if not m:
                continue
            campos = dict(par.split("=", 1) for par in m.group(2).split())
            clave = campos.get("archivo") if m.group(1) == "clip" else campos.get("revision")
            if clave:
                salida[m.group(1)][clave] = {k: (float(v) if re.fullmatch(r"-?[\d.]+", v) else v)
                                              for k, v in campos.items()}
    return salida


def inferencia_ms(psql: list[str], revisiones: list[str]) -> dict[str, float]:
    """Consulta `clasificacion.latencia_inferencia_ms` de las revisiones dadas.

    Args:
        psql: comando que ejecuta `psql` contra la base de la prueba.
        revisiones: `revision_id` a consultar.

    Returns:
        `{revision_id: latencia_inferencia_ms}` solo de las que tienen valor.
    """
    if not revisiones:
        return {}
    ids = ",".join(f"'{r}'" for r in revisiones)
    sql = (f"SELECT r.id, c.latencia_inferencia_ms FROM sabre.revision_var r "
           f"JOIN sabre.clasificacion c ON c.tocado_id = r.tocado_id "
           f"WHERE r.id IN ({ids}) AND c.latencia_inferencia_ms IS NOT NULL")
    r = subprocess.run([*psql, "-At", "-F", ",", "-c", sql], capture_output=True, text=True, check=True)
    return {a: float(b) for a, b in (linea.split(",") for linea in r.stdout.splitlines() if linea)}


def desglosar(registro: dict, log: dict, inferencia: dict) -> dict:
    """Calcula las etapas de una solicitud.

    Args:
        registro: línea del JSONL de `carga.py`.
        log: salida de `leer_log`.
        inferencia: salida de `inferencia_ms`.

    Returns:
        El registro con las etapas añadidas (las que no se pudieron medir quedan en None).
    """
    clip = log["clip"].get(registro["archivo"])
    rev = registro.get("revision_id")
    feat = log["features"].get(rev) if rev else None
    nube = log["espera_cloud"].get(rev) if rev else None
    etapas = {"subida": registro.get("subida_s"), "cola_executor": None, "cola_yolo": None, "pose": None,
              "features": None, "cloud_espera": None, "clasificacion": None, "resto": None}
    if clip:
        # `finish()` no calcula nada, pero entra por el mismo executor de 2 hilos: su espera es cola.
        etapas["cola_executor"] = clip["espera_executor_s"] + clip["finish_y_guardado_s"]
        etapas["cola_yolo"] = clip["espera_cola_pose_s"]
        etapas["pose"] = clip["lectura_y_pose_s"] - clip["espera_cola_pose_s"]
    if feat:
        etapas["features"] = feat["espera_executor_s"] + feat["features_s"] + feat["publicar_s"]
    if nube and rev in inferencia:
        etapas["clasificacion"] = inferencia[rev] / 1000
        etapas["cloud_espera"] = nube["espera_s"] - etapas["clasificacion"]
    elif nube:
        etapas["cloud_espera"] = nube["espera_s"]
    medidas = [v for k, v in etapas.items() if k != "resto" and v is not None]
    etapas["resto"] = registro["total_s"] - sum(medidas) if len(medidas) >= 5 else None
    return {**registro, "etapas": etapas, "frames": clip["frames"] if clip else None}


def resumir(grupo: list[dict]) -> dict:
    """Resume un grupo de solicitudes: n, p50, p95 y medias por etapa, y clips no disponibles.

    Args:
        grupo: solicitudes ya desglosadas.

    Returns:
        Diccionario con `n`, `p50`, `p95`, `max`, `no_disponibles`, `fuera_de_60s` y `etapas_media`.
    """
    tot = [r["total_s"] for r in grupo]
    etapas = {}
    for nombre in ("subida", "cola_executor", "cola_yolo", "pose", "features", "cloud_espera",
                   "clasificacion", "resto"):
        v = [r["etapas"][nombre] for r in grupo if r["etapas"].get(nombre) is not None]
        etapas[nombre] = sum(v) / len(v) if v else None
    return {
        "n": len(grupo), "p50": percentil(tot, 50), "p95": percentil(tot, 95), "max": max(tot) if tot else None,
        "no_disponibles": sum(1 for r in grupo if not r.get("disponible")),
        "fuera_de_60s": sum(1 for r in grupo if r["fuera_de_60s"]),
        "etapas_media": etapas,
    }


def main() -> None:
    """Desglosa las solicitudes y escribe el resumen en JSON."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--fog-log", required=True)
    ap.add_argument("--fog-log-desde", type=int, default=0)
    ap.add_argument("--recursos", default="")
    ap.add_argument("--psql", default="docker exec -i sabre-postgres-1 psql -U sabre -d sabre_estres")
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    registros = [json.loads(linea) for ruta in args.jsonl.split(",") for linea in open(ruta) if linea.strip()]
    log = leer_log(Path(args.fog_log), args.fog_log_desde)
    inf = inferencia_ms(args.psql.split(), [r["revision_id"] for r in registros if r.get("revision_id")])
    desglosados = [desglosar(r, log, inf) for r in registros]
    por_grupo: dict[str, list[dict]] = defaultdict(list)
    for r in desglosados:
        por_grupo[f"{r['escenario']}_n{r['pistas']}"].append(r)
    resumen = {g: resumir(v) for g, v in sorted(por_grupo.items())}
    recursos = {}
    for ruta in filter(None, args.recursos.split(",")):
        for etiqueta, maximos in _recursos_por_corrida(Path(ruta)).items():
            recursos.setdefault(etiqueta, {}).update(maximos)
    Path(args.salida).write_text(json.dumps(
        {"resumen": resumen, "recursos_max": recursos, "solicitudes": desglosados}, indent=2, ensure_ascii=False))
    for g, r in resumen.items():
        print(g, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items() if k != "etapas_media"})


def _recursos_por_corrida(ruta: Path) -> dict[str, dict[str, float]]:
    """Máximos de CPU y RAM por grupo `escenario_n` según la etiqueta de cada fila.

    Args:
        ruta: CSV del medidor.

    Returns:
        `{"A_n4": {columna: máximo}}`; las etiquetas `A_n4_r0` se agrupan en `A_n4`.
    """
    grupos: dict[str, dict[str, float]] = {}
    with open(ruta, newline="") as f:
        for fila in csv.DictReader(f):
            etiqueta = re.sub(r"_r\d+$", "", fila["etiqueta"])
            if not etiqueta:
                continue
            g = grupos.setdefault(etiqueta, {})
            for k, v in fila.items():
                if k in ("t_s", "etiqueta") or v in ("", None):
                    continue
                g[k] = max(g.get(k, 0.0), float(v))
    return grupos


if __name__ == "__main__":
    main()
