"""Recorte del clip: remuestreo a fps constante y escritura de MP4 H.264 (EDGE01)."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edge.captura.buffer import FrameMarcado


class ErrorClip(Exception):
    """No se pudo armar o escribir el clip."""


@dataclass(frozen=True)
class ClipRemuestreado:
    """Frames a fps constante, con el tiempo del clip igual al de captura.

    Attributes:
        imagenes: un frame por cada instante `t0_ns + i/fps`.
        t0_ns: instante de captura del primer frame (el cero del clip).
        fps: cuadros por segundo.
        repetidos: frames que se repitieron porque la cámara entregó menos de los esperados.
    """

    imagenes: list[Any]
    t0_ns: int
    fps: int
    repetidos: int


def remuestrear(frames: Sequence[FrameMarcado], fps: int, hasta_ns: int) -> ClipRemuestreado:
    """Pasa los frames (con jitter) a una grilla de `fps` constante desde el primero.

    Para cada instante de la grilla toma el frame de captura más cercano. Así el tiempo dentro
    del MP4 (`i / fps`) coincide con el instante de captura, con error menor que medio frame, y
    los instantes de luz relativos a `t0_ns` valen también para el video.

    Args:
        frames: frames en orden de llegada (al menos uno).
        fps: cuadros por segundo del clip.
        hasta_ns: instante final deseado; la grilla termina antes si el último frame llegó antes.

    Returns:
        El clip remuestreado.

    Raises:
        ErrorClip: si no hay frames o `fps` no es positivo.
    """
    if not frames:
        raise ErrorClip("no hay frames en la ventana del tocado")
    if fps <= 0:
        raise ErrorClip("fps debe ser positivo")
    t0 = frames[0].t_ns
    fin = min(hasta_ns, frames[-1].t_ns)
    periodo_ns = 1e9 / fps
    n = int((fin - t0) // periodo_ns) + 1
    imagenes: list[Any] = []
    repetidos = 0
    j = 0
    anterior = -1
    for i in range(n):
        objetivo = t0 + i * periodo_ns
        while j + 1 < len(frames) and abs(frames[j + 1].t_ns - objetivo) <= abs(frames[j].t_ns - objetivo):
            j += 1
        if j == anterior:
            repetidos += 1
        anterior = j
        imagenes.append(frames[j].imagen)
    return ClipRemuestreado(imagenes, t0, fps, repetidos)


def escribir_mp4(ruta: Path, imagenes: Sequence[Any], fps: int) -> None:
    """Escribe un MP4 H.264 ('avc1') de forma atómica (archivo temporal y renombrado).

    Args:
        ruta: destino `.mp4`.
        imagenes: frames BGR, todos del mismo tamaño.
        fps: cuadros por segundo.

    Raises:
        ErrorClip: si no hay frames o OpenCV no puede abrir el codificador H.264.
    """
    import cv2  # import local: el buffer y los instantes se prueban sin OpenCV

    if not imagenes:
        raise ErrorClip("no hay frames que escribir")
    alto, ancho = imagenes[0].shape[:2]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.stem + ".parcial.mp4")
    escritor = cv2.VideoWriter(str(temporal), cv2.VideoWriter_fourcc(*"avc1"), fps, (ancho, alto))
    if not escritor.isOpened():
        escritor.release()
        raise ErrorClip("OpenCV no pudo abrir el codificador H.264 (avc1) en este equipo")
    try:
        for imagen in imagenes:
            escritor.write(imagen)
    finally:
        escritor.release()
    if not temporal.exists() or temporal.stat().st_size == 0:
        raise ErrorClip(f"el MP4 quedó vacío: {temporal}")
    os.replace(temporal, ruta)
