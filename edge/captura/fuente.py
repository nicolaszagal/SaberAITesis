"""Hilo que lee la cámara y llena el buffer circular (EDGE01).

Lee con `cv2.VideoCapture` (índice de cámara o ruta de un video pregrabado) y marca cada frame
con `time.monotonic_ns()` al terminar `read()`. Con un archivo de video avanza al ritmo de sus
fps para imitar una cámara en vivo (se repite al llegar al final). La elección y configuración
de la cámara (EDGE02) no están aquí: solo lo mínimo para alimentar el buffer.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from edge.captura.buffer import BufferCircular

logger = logging.getLogger(__name__)


class HiloCaptura:
    """Lee frames de una fuente y los agrega al buffer."""

    def __init__(
        self,
        fuente: int | str,
        buffer: BufferCircular | None,
        *,
        fps: int = 30,
        ancho: int | None = None,
        alto: int | None = None,
        al_ritmo_del_archivo: bool = False,
        reloj_ns: Callable[[], int] = time.monotonic_ns,
        al_frame: Callable[[Any, int], None] | None = None,
    ) -> None:
        """Prepara la captura (no abre nada hasta `iniciar`).

        Args:
            fuente: índice de cámara (0, 1...) o ruta de un video.
            buffer: destino de los frames (`None` si solo se usa `al_frame`).
            fps: fps que se piden a la cámara y a los que se pacea un archivo.
            ancho: ancho pedido a la cámara (`None` = el de la cámara).
            alto: alto pedido a la cámara.
            al_ritmo_del_archivo: si es un archivo, esperar para entregar `fps` frames por segundo.
            reloj_ns: reloj monótono.
            al_frame: se llama con (imagen, t_ns) por cada frame, desde el hilo de captura.
        """
        self._fuente = fuente
        self._buffer = buffer
        self._fps = fps
        self._ancho = ancho
        self._alto = alto
        self._pacear = al_ritmo_del_archivo
        self._reloj_ns = reloj_ns
        self._al_frame = al_frame
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._listo = threading.Event()
        self.error: str | None = None
        self.frames_leidos = 0
        self.fps_medidos = 0.0
        self.huecos = 0  # veces que pasó más de 1,5 periodos entre dos frames
        self.ancho = 0
        self.alto = 0

    def iniciar(self, espera_apertura_s: float = 5.0) -> None:
        """Abre la fuente y arranca el hilo.

        Args:
            espera_apertura_s: cuánto esperar a que la fuente abra.

        Raises:
            RuntimeError: si la fuente no abre (permiso de cámara, índice inexistente, archivo roto).
        """
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="captura-camara", daemon=True)
        self._hilo.start()
        if not self._listo.wait(espera_apertura_s) or self.error:
            raise RuntimeError(self.error or "la cámara no abrió a tiempo")

    def detener(self, timeout_s: float = 2.0) -> None:
        """Detiene el hilo y libera la cámara."""
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout_s)

    def _abrir(self) -> Any:
        import cv2

        cap = cv2.VideoCapture(self._fuente)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"no se pudo abrir la fuente de video {self._fuente!r}")
        if isinstance(self._fuente, int):
            if self._ancho:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._ancho)
            if self._alto:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._alto)
            cap.set(cv2.CAP_PROP_FPS, self._fps)
        return cap

    def _bucle(self) -> None:
        try:
            cap = self._abrir()
        except Exception as error:  # noqa: BLE001
            self.error = str(error)
            self._listo.set()
            return
        self._listo.set()
        es_archivo = isinstance(self._fuente, str)
        inicio = self._reloj_ns()
        proximo = inicio
        ultimo_ns = inicio
        try:
            while not self._parar.is_set():
                ok, imagen = cap.read()
                t_ns = self._reloj_ns()
                if not ok:
                    if es_archivo:
                        import cv2

                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # repetir el video
                        continue
                    logger.error("[Captura] La cámara dejó de entregar frames")
                    self.error = "la cámara dejó de entregar frames"
                    return
                if self._buffer is not None:
                    self._buffer.agregar(imagen, t_ns)
                if self._al_frame is not None:
                    self._al_frame(imagen, t_ns)
                if self.frames_leidos and (t_ns - ultimo_ns) > 1.5e9 / self._fps:
                    self.huecos += 1
                ultimo_ns = t_ns
                if not self.ancho:
                    self.alto, self.ancho = imagen.shape[:2]
                self.frames_leidos += 1
                transcurrido = (t_ns - inicio) / 1e9
                if transcurrido > 0:
                    self.fps_medidos = self.frames_leidos / transcurrido
                if es_archivo and self._pacear:
                    proximo += int(1e9 / self._fps)
                    pausa = (proximo - self._reloj_ns()) / 1e9
                    if pausa > 0:
                        self._parar.wait(pausa)
        finally:
            cap.release()
