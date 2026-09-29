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

import asyncio
import logging
import os
import tempfile
from concurrent.futures import Executor
from dataclasses import dataclass
from pathlib import Path

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
) -> ClipProcesado:
    """Valida el clip subido, corre pose+tracking y lo guarda por SHA-256.

    Args:
        file: archivo multipart recibido.
        pose_estimator: puerto de pose+tracking.
        executor: hilos para el trabajo de CPU.
        storage: almacén donde se guarda el clip (uri + sha256).
        clip_max_mb: tamaño máximo aceptado.
        min_frames: frames mínimos para aceptar el clip.

    Returns:
        Secuencia rastreada, uri/sha256 del archivo y metadatos de video.

    Raises:
        ClipTooLargeError: si supera `clip_max_mb`.
        InvalidClipError: si no abre como video, no informa fps válidos o
            tiene menos de `min_frames` frames.
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

        n_frames, fps, ancho, alto = await loop.run_in_executor(executor, _read_all_frames)
        tracked = await loop.run_in_executor(executor, pose_session.finish)
        uri, sha256 = await storage.save_clip(Path(tmp_path))
        log.info("clip subido (%s): %d frames procesados", file.filename, n_frames)
        return ClipProcesado(
            tracked=tracked,
            uri=uri,
            sha256=sha256,
            fps=round(fps, 2),
            ancho_px=ancho,
            alto_px=alto,
            duracion_ms=max(1, round(n_frames / fps * 1000)),
        )
    finally:
        os.remove(tmp_path)
