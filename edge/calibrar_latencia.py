"""Calibración del desfase entre la señal serie del Favero y el video (RF-06, EDGE01).

Se filma una luz del aparato (o del repetidor) mientras se dan ≥ 20 toques. Para cada toque se
compara el instante serie del flanco (`time.monotonic_ns()` al llegar la trama) con el primer
frame en que la luz se ve encendida (brillo medio de una región marcada a mano sobre un umbral):

    desfase = t_primer_frame_encendido − t_serie        (positivo = el video llega después)

El desfase agrupa la latencia de la cámara y la del camino serie (el aparato manda la luz en la
siguiente trama, que tarda ~42 ms en transmitirse, y el puente USB). `CapturaTocados` lo suma al
instante serie para ubicar la luz en el video. Se guarda por cámara en
`datos/edge/latencia_camara.json`.

    python -m edge.calibrar_latencia --puerto '/dev/cu.usbmodem*' --camara 0 \\
        --roi-roja 600,300,40,40 --roi-verde 700,300,40,40 --toques 20

Sin `--roi-*` se puede marcar con el ratón (`--elegir-roi`, requiere OpenCV con ventanas).
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import threading
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge.captura.config import ConfigCaptura
from edge.favero.lector import BAUDIOS_USB, Flanco, LectorFavero

logger = logging.getLogger(__name__)

ANTES_S = 0.15  # la luz puede verse un poco "antes" del flanco serie si el camino serie es lento
DESPUES_S = 1.0  # tiempo máximo en que se espera ver la luz tras el flanco serie


def brillo_roi(imagen: Any, roi: tuple[int, int, int, int]) -> float:
    """Brillo medio (0-255) de una región.

    Args:
        imagen: frame BGR o en grises.
        roi: (x, y, ancho, alto).

    Returns:
        Promedio de los píxeles de la región, en escala de grises.
    """
    x, y, w, h = roi
    recorte = imagen[y : y + h, x : x + w]
    if recorte.ndim == 3:
        recorte = recorte[..., :3].mean(axis=2)
    return float(recorte.mean())


def umbral_automatico(brillos: Sequence[float]) -> float:
    """Punto medio entre el brillo mínimo y el máximo de la sesión (luz apagada y encendida)."""
    return (min(brillos) + max(brillos)) / 2


def subidas_camara(serie: Sequence[tuple[int, float]], umbral: float) -> list[int]:
    """Instantes del primer frame con brillo sobre el umbral tras estar bajo él.

    Args:
        serie: pares (t_ns, brillo) en orden.
        umbral: brillo desde el cual la luz se considera encendida.

    Returns:
        Los t_ns de cada subida.
    """
    subidas = []
    encendida = False
    for t_ns, brillo in serie:
        ahora = brillo >= umbral
        if ahora and not encendida:
            subidas.append(t_ns)
        encendida = ahora
    return subidas


def emparejar(serie_ns: Sequence[int], camara_ns: Sequence[int]) -> tuple[list[float], int]:
    """Empareja cada flanco serie con la primera subida de cámara en `[S − 0,15 s, S + 1 s]`.

    Cada subida de cámara se usa una sola vez.

    Args:
        serie_ns: instantes de los flancos serie de una luz.
        camara_ns: instantes de las subidas de esa luz en el video.

    Returns:
        (desfases en ms = cámara − serie, cantidad de flancos serie sin pareja).
    """
    desfases: list[float] = []
    sin_pareja = 0
    usadas: set[int] = set()
    for s in serie_ns:
        for i, c in enumerate(camara_ns):
            if i in usadas:
                continue
            if s - ANTES_S * 1e9 <= c <= s + DESPUES_S * 1e9:
                desfases.append((c - s) / 1e6)
                usadas.add(i)
                break
        else:
            sin_pareja += 1
    return desfases, sin_pareja


def resumir(desfases: Sequence[float]) -> dict[str, float | int]:
    """Estadísticos del desfase.

    Args:
        desfases: desfases en ms (al menos uno).

    Returns:
        n, media, desviación estándar (0 si hay uno), mínimo, máximo, y el error máximo que queda
        tras restar la media (`residuo_max_ms`).

    Raises:
        ValueError: si no hay desfases.
    """
    if not desfases:
        raise ValueError("no hay toques emparejados")
    media = statistics.fmean(desfases)
    return {
        "n": len(desfases),
        "desfase_ms": media,
        "desviacion_ms": statistics.stdev(desfases) if len(desfases) > 1 else 0.0,
        "minimo_ms": min(desfases),
        "maximo_ms": max(desfases),
        "residuo_max_ms": max(abs(d - media) for d in desfases),
    }


def guardar(archivo: Path, camara_id: str, resultado: dict[str, Any]) -> None:
    """Agrega o reemplaza la calibración de una cámara, sin tocar las de las demás."""
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    datos[camara_id] = resultado
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def calibrar(
    flancos: Sequence[Flanco],
    series: dict[str, Sequence[tuple[int, float]]],
    umbrales: dict[str, float | None],
) -> dict[str, Any]:
    """Calcula el desfase con los flancos serie y el brillo por luz.

    Args:
        flancos: flancos del lector (ROJA/VERDE).
        series: por luz ("ROJA"/"VERDE"), la serie (t_ns, brillo) de su región.
        umbrales: por luz, umbral de brillo; `None` = automático.

    Returns:
        Resultado agrupado (`desfase_ms`, `desviacion_ms`...) más el detalle `por_luz`.

    Raises:
        ValueError: si ningún toque quedó emparejado.
    """
    todos: list[float] = []
    por_luz: dict[str, Any] = {}
    for luz, serie in series.items():
        if not serie:
            continue
        umbral = umbrales.get(luz) or umbral_automatico([b for _, b in serie])
        subidas = subidas_camara(serie, umbral)
        serie_ns = [f.t_ns for f in flancos if f.luz == luz]
        desfases, sin_pareja = emparejar(serie_ns, subidas)
        por_luz[luz] = {
            "toques_serie": len(serie_ns),
            "subidas_camara": len(subidas),
            "sin_pareja": sin_pareja,
            "umbral": umbral,
            **(resumir(desfases) if desfases else {"n": 0}),
        }
        todos.extend(desfases)
    return {**resumir(todos), "por_luz": por_luz}


def _roi(texto: str) -> tuple[int, int, int, int]:
    x, y, w, h = (int(v) for v in texto.split(","))
    return x, y, w, h


def principal(argv: list[str] | None = None) -> int:
    """Corre la calibración interactiva.

    Args:
        argv: argumentos (por defecto `sys.argv`).

    Returns:
        0 si se guardó la calibración; 1 si faltó algo (cámara, regiones o toques emparejados).
    """
    import cv2

    from edge.captura.fuente import HiloCaptura

    parser = argparse.ArgumentParser(description="Calibra el desfase serie Favero ↔ video.")
    parser.add_argument("--puerto", default="/dev/cu.usbmodem*")
    parser.add_argument("--baudios", type=int, default=BAUDIOS_USB)
    parser.add_argument("--camara", default="0", help="índice o ruta de video")
    parser.add_argument("--camara-id", default="frontal")
    parser.add_argument("--roi-roja", type=_roi, help="x,y,ancho,alto de la luz roja en el video")
    parser.add_argument("--roi-verde", type=_roi, help="x,y,ancho,alto de la luz verde en el video")
    parser.add_argument("--elegir-roi", action="store_true", help="marcar las regiones con el ratón")
    parser.add_argument("--umbral", type=float, default=None, help="brillo de 'encendida' (por defecto, punto medio)")
    parser.add_argument("--toques", type=int, default=20, help="toques mínimos por luz antes de terminar")
    parser.add_argument("--segundos", type=float, default=600.0, help="tiempo máximo de la sesión")
    parser.add_argument("--ancho", type=int, default=1280)
    parser.add_argument("--alto", type=int, default=720)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = ConfigCaptura.desde_entorno()

    fuente: int | str = int(args.camara) if args.camara.isdigit() else args.camara
    rois = {"ROJA": args.roi_roja, "VERDE": args.roi_verde}
    if args.elegir_roi:
        cap = cv2.VideoCapture(fuente)
        ok, primero = cap.read()
        cap.release()
        if not ok:
            logger.error("No se pudo leer un frame para marcar las regiones")
            return 1
        for luz in ("ROJA", "VERDE"):
            r = cv2.selectROI(f"Marca la luz {luz} y pulsa Enter (Esc para omitir)", primero)
            cv2.destroyAllWindows()
            rois[luz] = tuple(int(v) for v in r) if r[2] and r[3] else None
    rois = {luz: r for luz, r in rois.items() if r}
    if not rois:
        logger.error("Falta al menos una región (--roi-roja, --roi-verde o --elegir-roi)")
        return 1

    series: dict[str, list[tuple[int, float]]] = {luz: [] for luz in rois}
    lock = threading.Lock()

    def al_frame(imagen: Any, t_ns: int) -> None:
        for luz, roi in rois.items():
            b = brillo_roi(imagen, roi)
            with lock:
                series[luz].append((t_ns, b))

    flancos: list[Flanco] = []
    lector = LectorFavero(args.puerto, flancos.append, baudios=args.baudios)
    camara = HiloCaptura(fuente, None, fps=config.fps, ancho=args.ancho, alto=args.alto, al_frame=al_frame)
    try:
        camara.iniciar()
    except RuntimeError as error:
        logger.error("%s", error)
        return 1
    lector.iniciar()
    print(f"Da {args.toques} toques por cada luz con región marcada (reinicia el aparato entre toques).")
    print("Ctrl+C termina antes.")
    fin = time.monotonic() + args.segundos
    try:
        while time.monotonic() < fin:
            time.sleep(0.5)
            cuenta = {luz: sum(1 for f in flancos if f.luz == luz) for luz in rois}
            if all(c >= args.toques for c in cuenta.values()):
                break
    except KeyboardInterrupt:
        pass
    lector.detener()
    camara.detener()

    with lock:
        copia = {luz: list(s) for luz, s in series.items()}
    try:
        resultado = calibrar(flancos, copia, {luz: args.umbral for luz in rois})
    except ValueError:
        logger.error("Ningún toque quedó emparejado: revisa la región, el umbral y la iluminación")
        return 1
    resultado.update(
        {
            "fps_medidos": camara.fps_medidos,
            "regiones": {luz: list(r) for luz, r in rois.items()},
            "fecha_utc": datetime.now(timezone.utc).isoformat(),
            "tramas_invalidas": lector.estado()["tramas_invalidas"],
            "huecos": lector.estado()["huecos"],
        }
    )
    guardar(config.archivo_latencia, args.camara_id, resultado)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    print(
        f"\nDesfase medio {resultado['desfase_ms']:.1f} ms, desviación {resultado['desviacion_ms']:.1f} ms, "
        f"residuo máximo {resultado['residuo_max_ms']:.1f} ms (n={resultado['n']}). "
        f"Guardado en {config.archivo_latencia}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
