"""CameraCapture — envoltorio de cv2.VideoCapture para una cámara RTSP:
abre/reabre la conexión, lee un frame y lo codifica a JPEG.

Bloqueante a propósito (cv2.VideoCapture.read/imencode no son async): el
orquestador (ws_bridge.py) lo corre en un ThreadPoolExecutor desde su loop
async, mismo patrón que fog usa para correr YOLO fuera del loop (ver
fog/infrastructure/pose/yolo_pose_adapter.py).
"""

from __future__ import annotations

import logging
import time

import cv2

logger = logging.getLogger(__name__)

_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 8.0


class CameraCapture:
    def __init__(self, name: str, rtsp_url: str, jpeg_quality: int):
        self._name = name
        self._rtsp_url = rtsp_url
        self._jpeg_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        self._cap: cv2.VideoCapture | None = None
        self._backoff_s = _INITIAL_BACKOFF_S
        self._next_attempt_at = 0.0
        self._reconnecting = False

    def read_frame(self) -> bytes | None:
        """Lee y codifica un frame a JPEG. None si todavía no toca
        reintentar la conexión (en backoff), si la lectura falló recién
        (stream cortado), o si la codificación JPEG falló — en los tres
        casos el caller (stream_loop) simplemente reintenta en el próximo
        tick, sin romper el loop."""
        if self._cap is None and not self._connect():
            return None

        ok, frame = self._cap.read()
        if not ok:
            self._disconnect()
            return None

        ok, encoded = cv2.imencode(".jpg", frame, self._jpeg_params)
        if not ok:
            logger.warning("[Edge][%s] No se pudo codificar el frame a JPEG", self._name)
            return None

        return encoded.tobytes()

    def _connect(self) -> bool:
        if time.monotonic() < self._next_attempt_at:
            return False

        cap = cv2.VideoCapture(self._rtsp_url)
        if not cap.isOpened():
            cap.release()
            self._schedule_retry()
            return False

        self._cap = cap
        self._backoff_s = _INITIAL_BACKOFF_S
        if self._reconnecting:
            logger.info("[Edge][%s] Stream restaurado", self._name)
            self._reconnecting = False
        return True

    def _disconnect(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._schedule_retry()

    def _schedule_retry(self) -> None:
        self._reconnecting = True
        logger.warning(
            "[Edge][%s] Stream perdido, reconectando en %ds...", self._name, int(self._backoff_s)
        )
        self._next_attempt_at = time.monotonic() + self._backoff_s
        self._backoff_s = min(self._backoff_s * 2, _MAX_BACKOFF_S)
