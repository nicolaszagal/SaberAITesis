"""process_uploaded_clip — lee un clip de video subido por HTTP
(multipart, POST /matches/{match_id}/clip) frame a frame, igual que
track_consumer.py hace con los frames que llegan por WebRTC, pero desde
un archivo en disco en vez de una pista en vivo.

Vive en infrastructure/ (no en application/) porque depende directamente
de cv2 y del filesystem temporal — application/ (ProcessIncomingMatch) no
debe saber cómo se obtuvo la TrackedSequence, solo consumirla.

No usa el patrón producer/consumer de track_consumer.py: ese patrón existe
para solapar la espera de red (track.recv()) con el procesamiento de CPU.
Acá el archivo ya está completo en disco antes de empezar — no hay espera
de red que solapar. El cuello de botella es el mismo en ambos casos
(tiempo de inferencia de YOLO por frame), así que un loop secuencial
simple alcanza. cv2.VideoCapture(path) es la misma convención que usa
dataset/05_extract_features.py para leer clips del dataset.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import asyncio
import logging
import os
import tempfile
import threading
from concurrent.futures import Executor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
from fastapi import UploadFile

from fog.domain.models import TrackedSequence
from fog.ports.file_storage import FileStoragePort
from fog.ports.pose_estimator import PoseEstimatorPort

log = logging.getLogger("fog.infrastructure.clips")


class ClipTooLargeError(Exception):
    """El archivo subido supera CLIP_MAX_MB (DEF-13). El router lo traduce a HTTP 413."""


class InvalidClipError(Exception):
    """El archivo subido no abre con cv2 o tiene menos de MIN_FRAMES frames
    (DEF-13). El router lo traduce a HTTP 400."""


class TocadoFueraDelClipError(Exception):
    """El instante de una luz (o `t_tocado_ms` obsoleto) no está entre 0 y la
    duración del clip. El router lo traduce a HTTP 422."""


@dataclass(frozen=True)
class ClipGuardado:
    """Clip guardado por SHA-256 con sus metadatos de video, sin pose."""

    uri: str
    sha256: str
    fps: float
    ancho_px: int
    alto_px: int
    duracion_ms: int


class ExtraccionAgotadaError(Exception):
    """La extracción de pose superó el plazo (DEF-08, RF-13, RNF-09).

    El clip ya quedó guardado en `clip`, para abrir la revisión sin
    clasificación. El router lo traduce a "no disponible" con motivo `timeout`.
    """

    def __init__(self, clip: ClipGuardado):
        super().__init__("la extracción de pose superó el plazo")
        self.clip = clip


class _ExtraccionCancelada(Exception):
    """Interna: corta el hilo de lectura de frames tras un timeout."""


@dataclass(frozen=True)
class ClipProcesado:
    """Clip subido ya procesado y guardado: pose+tracking y metadatos de
    video para `sabre.clip`."""

    tracked: TrackedSequence
    uri: str
    sha256: str
    fps: float
    ancho_px: int
    alto_px: int
    duracion_ms: int


async def process_uploaded_clip(
    file: UploadFile,
    pose_estimator: PoseEstimatorPort,
    executor: Executor,
    storage: FileStoragePort,
    clip_max_mb: float,
    min_frames: int,
    instantes_ms: Mapping[str, int] | None = None,
    plazo_s: float | None = None,
) -> ClipProcesado:
    """Valida el clip subido, corre pose+tracking y lo guarda por SHA-256.

    Args:
        file: archivo multipart recibido.
        pose_estimator: puerto de pose+tracking.
        executor: hilos para el trabajo de CPU.
        storage: almacén donde se guarda el clip (uri + sha256).
        clip_max_mb: tamaño máximo aceptado.
        min_frames: frames mínimos para aceptar el clip.
        instantes_ms: instantes simulados por nombre de campo (`t_luz_a_ms`,
            `t_luz_b_ms`); cada uno debe estar entre 0 y la duración del clip
            (ambos incluidos).
        plazo_s: segundos máximos para la extracción de pose; None = sin límite.

    Returns:
        Secuencia rastreada, uri/sha256 del archivo y metadatos de video.

    Raises:
        ClipTooLargeError: si supera `clip_max_mb`.
        InvalidClipError: si no abre como video, no informa fps válidos o
            tiene menos de `min_frames` frames.
        TocadoFueraDelClipError: si algún instante es negativo o supera la
            duración del clip. El clip no se guarda.
        ExtraccionAgotadaError: si la pose no termina en `plazo_s`. El hilo de
            lectura se cancela y el clip se guarda; la excepción lo trae.
    """
    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    content = await file.read()

    max_bytes = clip_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ClipTooLargeError(
            f"el clip subido ({file.filename!r}) pesa "
            f"{len(content) / (1024 * 1024):.1f} MB, el máximo es {clip_max_mb:.0f} MB"
        )

    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(content)

        loop = asyncio.get_running_loop()
        limite = None if plazo_s is None else loop.time() + plazo_s
        cancelar = threading.Event()
        pose_session = pose_estimator.start_session()

        def _read_all_frames() -> tuple[int, float, int, int]:
            cap = cv2.VideoCapture(tmp_path)
            if not cap.isOpened():
                raise InvalidClipError(f"no se pudo abrir el clip subido ({file.filename!r})")
            n = 0
            alto = ancho = 0
            fps = cap.get(cv2.CAP_PROP_FPS)
            try:
                while True:
                    if cancelar.is_set():
                        raise _ExtraccionCancelada()
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if n == 0:
                        alto, ancho = frame.shape[:2]
                    pose_session.add_frame(frame)
                    n += 1
            finally:
                cap.release()
            if n < min_frames:
                raise InvalidClipError(
                    f"el clip subido ({file.filename!r}) tiene {n} frames, "
                    f"se requieren al menos {min_frames}"
                )
            if not fps or fps <= 0:
                raise InvalidClipError(
                    f"el clip subido ({file.filename!r}) no informa una tasa de frames válida"
                )
            return n, float(fps), ancho, alto

        def _validar_instantes(duracion_ms: int) -> None:
            for nombre, valor in (instantes_ms or {}).items():
                if not 0 <= valor <= duracion_ms:
                    raise TocadoFueraDelClipError(
                        f"{nombre}={valor} está fuera del clip: debe estar entre 0 y "
                        f"{duracion_ms} ms (duración del clip {file.filename!r})"
                    )

        async def _con_plazo(trabajo: Callable[[], Any]) -> Any:
            restante = None if limite is None else max(0.0, limite - loop.time())
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, trabajo), restante
                )
            except asyncio.TimeoutError:
                cancelar.set()
                log.warning(
                    "clip %r: la extracción superó el plazo de %.0f s",
                    file.filename,
                    plazo_s,
                )
                guardado = await _guardar_sin_pose(
                    tmp_path, file.filename, storage, instantes_ms, _validar_instantes
                )
                raise ExtraccionAgotadaError(guardado) from None

        n_frames, fps, ancho, alto = await _con_plazo(_read_all_frames)
        duracion_ms = max(1, round(n_frames / fps * 1000))
        _validar_instantes(duracion_ms)
        tracked = await _con_plazo(pose_session.finish)
        uri, sha256 = await storage.save_clip(Path(tmp_path))
        log.info("clip subido (%s): %d frames procesados", file.filename, n_frames)
        return ClipProcesado(
            tracked=tracked,
            uri=uri,
            sha256=sha256,
            fps=round(fps, 2),
            ancho_px=ancho,
            alto_px=alto,
            duracion_ms=duracion_ms,
        )
    finally:
        os.remove(tmp_path)


async def _guardar_sin_pose(
    ruta: str,
    nombre: str | None,
    storage: FileStoragePort,
    instantes_ms: Mapping[str, int] | None,
    validar_instantes: Callable[[int], None],
) -> ClipGuardado:
    """Guarda el clip y lee sus metadatos sin correr pose (tras un timeout).

    La duración se calcula con los frames realmente leídos, no con
    CAP_PROP_FRAME_COUNT, que sobreestima los clips con preroll.

    Args:
        ruta: archivo temporal con el clip.
        nombre: nombre original del archivo, solo para los mensajes.
        storage: almacén donde se guarda el clip.
        instantes_ms: instantes de luz recibidos, validados contra la duración.
        validar_instantes: valida los instantes contra la duración estimada.

    Returns:
        El clip guardado y sus metadatos de video.

    Raises:
        InvalidClipError: si el clip no informa fps ni dimensiones válidos.
        TocadoFueraDelClipError: si un instante cae fuera de la duración.
    """
    cap = cv2.VideoCapture(ruta)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        # CAP_PROP_FRAME_COUNT cuenta paquetes de preroll (PTS negativo) que
        # read() no entrega; grab() recorre solo los frames reales.
        total = 0
        while cap.grab():
            total += 1
    finally:
        cap.release()
    if not fps or fps <= 0 or total <= 0 or not ancho or not alto:
        raise InvalidClipError(
            f"el clip subido ({nombre!r}) no informa fps ni dimensiones válidos"
        )
    duracion_ms = max(1, round(total / fps * 1000))
    validar_instantes(duracion_ms)
    uri, sha256 = await storage.save_clip(Path(ruta))
    return ClipGuardado(
        uri=uri, sha256=sha256, fps=round(float(fps), 2), ancho_px=ancho, alto_px=alto,
        duracion_ms=duracion_ms,
    )
