"""Buffer circular en RAM de los frames de la cámara (RF-04, F-015).

Guarda cada frame tal como lo entrega la cámara (arreglo BGR, sin recomprimir) junto con su
`time.monotonic_ns()`. Recién al recortar el clip se codifica a H.264.

Memoria: un frame BGR de 1280x720 pesa 2,76 MB; 5,5 s a 30 fps son 165 frames (~455 MB). Es el
precio de no recomprimir; con 1080p serían ~1 GB (ver `memoria_estimada_mb`).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FrameMarcado:
    """Un frame con su instante de llegada.

    Attributes:
        t_ns: `time.monotonic_ns()` al terminar de leer el frame de la cámara.
        imagen: arreglo BGR (alto, ancho, 3). No se copia: quien lo agrega no debe reutilizarlo.
    """

    t_ns: int
    imagen: Any


class BufferCircular:
    """Ventana deslizante de los últimos `capacidad_s` segundos de video. Seguro entre hilos."""

    def __init__(self, capacidad_s: float) -> None:
        """Crea el buffer.

        Args:
            capacidad_s: segundos que se conservan (el frame más nuevo menos el más viejo).

        Raises:
            ValueError: si la capacidad no es positiva.
        """
        if capacidad_s <= 0:
            raise ValueError("capacidad_s debe ser positiva")
        self.capacidad_s = capacidad_s
        self._capacidad_ns = int(capacidad_s * 1e9)
        self._frames: deque[FrameMarcado] = deque()
        self._lock = threading.Lock()
        self.frames_agregados = 0
        self.frames_descartados = 0

    def agregar(self, imagen: Any, t_ns: int) -> None:
        """Agrega un frame y descarta los que quedan fuera de la capacidad.

        Args:
            imagen: arreglo BGR del frame.
            t_ns: instante de llegada; no puede ser menor que el del frame anterior.

        Raises:
            ValueError: si `t_ns` retrocede (el reloj debe ser monótono).
        """
        with self._lock:
            if self._frames and t_ns < self._frames[-1].t_ns:
                raise ValueError("t_ns retrocede: el reloj del buffer debe ser monótono")
            self._frames.append(FrameMarcado(t_ns, imagen))
            self.frames_agregados += 1
            while t_ns - self._frames[0].t_ns > self._capacidad_ns:
                self._frames.popleft()
                self.frames_descartados += 1

    def extraer(self, desde_ns: int, hasta_ns: int) -> list[FrameMarcado]:
        """Frames con `desde_ns <= t_ns <= hasta_ns`, en orden. No los saca del buffer."""
        with self._lock:
            return [f for f in self._frames if desde_ns <= f.t_ns <= hasta_ns]

    def ultimo(self) -> FrameMarcado | None:
        """El frame más nuevo (para la vista previa), o `None` si está vacío."""
        with self._lock:
            return self._frames[-1] if self._frames else None

    def vaciar(self) -> None:
        """Descarta todos los frames (al cambiar de cámara o de resolución)."""
        with self._lock:
            self._frames.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

    @property
    def mas_viejo_ns(self) -> int | None:
        """Instante del frame más viejo, o `None` si está vacío."""
        with self._lock:
            return self._frames[0].t_ns if self._frames else None

    @property
    def mas_nuevo_ns(self) -> int | None:
        """Instante del frame más nuevo, o `None` si está vacío."""
        with self._lock:
            return self._frames[-1].t_ns if self._frames else None


def memoria_estimada_mb(capacidad_s: float, fps: float, ancho: int, alto: int) -> float:
    """Memoria del buffer lleno con frames BGR sin comprimir.

    Args:
        capacidad_s: segundos de capacidad.
        fps: cuadros por segundo.
        ancho: ancho en píxeles.
        alto: alto en píxeles.

    Returns:
        Megabytes (1 MB = 10^6 bytes).
    """
    return capacidad_s * fps * ancho * alto * 3 / 1e6
