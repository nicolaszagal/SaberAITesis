"""Mide RAM, CPU y fps del buffer circular con una cámara real (EDGE02): frames crudos vs JPEG en memoria.

    python -m edge.medir_buffer --camara 0 --segundos 20

Para cada modo ("crudo" = arreglo BGR tal como lo entrega OpenCV; "jpeg" = JPEG calidad 90 en memoria)
llena un buffer de `capacidad_buffer_s` segundos y reporta fps, frames perdidos (huecos de más de 1,5
periodos), RAM del proceso (RSS) y CPU del proceso (% de un núcleo). El resultado justifica el modo.
"""

from __future__ import annotations

import argparse
import os
import resource
import time

import cv2

from edge.captura.buffer import BufferCircular, memoria_estimada_mb
from edge.captura.config import ConfigCaptura


def _rss_mb() -> float:
    """RSS actual del proceso en MB (psutil si está; si no, el pico de `resource`)."""
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / 1e6
    except ImportError:
        pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return pico / 1e6 if os.uname().sysname == "Darwin" else pico / 1e3


def medir(camara: int | str, ancho: int, alto: int, fps: int, segundos: float, jpeg: bool, capacidad_s: float) -> dict:
    """Corre una medición.

    Args:
        camara: índice de OpenCV o ruta de un video (se reproduce al ritmo de `fps` y en bucle).
        ancho: ancho pedido.
        alto: alto pedido.
        fps: fps pedidos.
        segundos: duración de la medición (debe superar `capacidad_s` para llenar el buffer).
        jpeg: guardar JPEG en vez de frames crudos.
        capacidad_s: segundos del buffer.

    Returns:
        Diccionario con fps, huecos, RAM y CPU.

    Raises:
        RuntimeError: si la cámara no abre o no entrega frames.
    """
    cap = cv2.VideoCapture(camara)
    if not cap.isOpened():
        raise RuntimeError(f"no se pudo abrir la cámara {camara} (¿permiso de macOS?)")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
    cap.set(cv2.CAP_PROP_FPS, fps)
    buffer = BufferCircular(capacidad_s)
    rss0 = _rss_mb()
    n = huecos = 0
    anterior = None
    tam = None
    es_video = isinstance(camara, str)
    proximo = time.monotonic()
    cpu0, t0 = time.process_time(), time.monotonic()
    try:
        while time.monotonic() - t0 < segundos:
            ok, frame = cap.read()
            t_ns = time.monotonic_ns()
            if not ok:
                if es_video:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # repetir el video
                continue
            tam = frame.shape[:2]
            if anterior is not None and t_ns - anterior > 1.5e9 / fps:
                huecos += 1
            anterior = t_ns
            if jpeg:
                ok, frame = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            buffer.agregar(frame, t_ns)
            n += 1
            if es_video:  # imita una cámara: un frame cada 1/fps
                proximo += 1 / fps
                time.sleep(max(0.0, proximo - time.monotonic()))
    finally:
        cap.release()
    if not n:
        raise RuntimeError("la cámara no entregó frames")
    dur = time.monotonic() - t0
    return {
        "modo": "jpeg" if jpeg else "crudo", "resolucion": f"{tam[1]}x{tam[0]}", "frames": n,
        "fps_medidos": round(n / dur, 1), "huecos": huecos, "frames_en_buffer": len(buffer),
        "ram_buffer_mb": round(_rss_mb() - rss0), "cpu_pct_nucleo": round((time.process_time() - cpu0) / dur * 100),
    }


def principal(argv: list[str] | None = None) -> int:
    """Mide los dos modos y los imprime. Returns: 0."""
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--camara", default="0", help="índice de la cámara o ruta de un video")
    p.add_argument("--ancho", type=int, default=1280)
    p.add_argument("--alto", type=int, default=720)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--segundos", type=float, default=20.0)
    a = p.parse_args(argv)
    cap_s = ConfigCaptura().capacidad_buffer_s
    teorico = memoria_estimada_mb(cap_s, a.fps, a.ancho, a.alto)
    print(f"Buffer de {cap_s:.1f} s; teórico crudo a {a.ancho}x{a.alto}: {teorico:.0f} MB")
    for jpeg in (False, True):
        fuente = int(a.camara) if a.camara.isdigit() else a.camara
        print(medir(fuente, a.ancho, a.alto, a.fps, a.segundos, jpeg, cap_s), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
