"""ProcesadorClipPort — guardar un clip de tocado y extraer su pose por separado (EDGE02).

El tocado debe existir en cuanto llega el clip (para listarlo, reproducirlo y registrar la
decisión en pista), y la pose tarda segundos: por eso son dos pasos.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from fog.domain.models import TrackedSequence


@dataclass(frozen=True)
class ClipRecibido:
    """Clip validado, recortado a la ventana y guardado.

    Attributes:
        uri: URI en el almacén de archivos.
        sha256: hash del archivo guardado.
        fps: cuadros por segundo.
        ancho_px: ancho en píxeles.
        alto_px: alto en píxeles.
        duracion_ms: duración del clip guardado.
        desfase_recorte_ms: milisegundos que se quitaron al inicio (0 si no se recortó); hay
            que restarlos a los instantes de luz.
    """

    uri: str
    sha256: str
    fps: float
    ancho_px: int
    alto_px: int
    duracion_ms: int
    desfase_recorte_ms: int = 0


class ProcesadorClipPort(ABC):
    @abstractmethod
    async def guardar(
        self, contenido: bytes, nombre: str | None, instantes_ms: Mapping[str, int]
    ) -> ClipRecibido:
        """Valida, recorta a la ventana compartida y guarda el clip (sin pose).

        Raises:
            ClipTooLargeError: si supera el tamaño máximo.
            InvalidClipError: si no abre como video o tiene pocos frames.
            TocadoFueraDelClipError: si un instante cae fuera del clip.
        """
        raise NotImplementedError

    @abstractmethod
    async def extraer_pose(self, uri: str, plazo_s: float) -> TrackedSequence:
        """Corre pose+tracking sobre un clip ya guardado.

        Raises:
            ExtraccionAgotadaError: si no termina en `plazo_s`.
            InvalidClipError: si el archivo ya no existe o no se puede leer.
        """
        raise NotImplementedError
