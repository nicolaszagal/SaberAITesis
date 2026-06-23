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

import cv2
from fastapi import UploadFile

from fog.domain.models import TrackedSequence
from fog.ports.pose_estimator import PoseEstimatorPort

log = logging.getLogger("fog.infrastructure.clips")


async def process_uploaded_clip(
    file: UploadFile,
    pose_estimator: PoseEstimatorPort,
    executor: Executor,
) -> TrackedSequence:
    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    content = await file.read()

    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(content)

        loop = asyncio.get_running_loop()
        pose_session = pose_estimator.start_session()

        def _read_all_frames() -> int:
            cap = cv2.VideoCapture(tmp_path)
            if not cap.isOpened():
                raise ValueError(f"no se pudo abrir el clip subido ({file.filename!r})")
            n = 0
            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    pose_session.add_frame(frame)
                    n += 1
            finally:
                cap.release()
            return n

        n_frames = await loop.run_in_executor(executor, _read_all_frames)
        tracked = await loop.run_in_executor(executor, pose_session.finish)
        log.info("clip subido (%s): %d frames procesados", file.filename, n_frames)
        return tracked
    finally:
        os.remove(tmp_path)
