"""Cámaras del Mac: listado, apertura con la resolución pedida y medición de fps (EDGE02, RF-03, RNF-13).

Permiso de macOS: la primera vez que se abre una cámara, macOS pide permiso a la aplicación que
corre Python (Terminal, iTerm, VS Code...). Si se negó: Ajustes del Sistema → Privacidad y
seguridad → Cámara, y activar esa aplicación. Sin permiso `cv2.VideoCapture` abre pero no entrega
frames, y `HiloCaptura.iniciar` lo informa como error.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ALTO_MIN = 720  # RNF-13
FPS_MIN = 30  # RNF-13


@dataclass(frozen=True)
class Camara:
    """Dispositivo de video.

    Attributes:
        indice: índice que se pasa a `cv2.VideoCapture` (orden de AVFoundation).
        nombre: nombre del dispositivo.
    """

    indice: int
    nombre: str


def parsear_ffmpeg(salida: str) -> list[Camara]:
    """Extrae las cámaras de la salida de `ffmpeg -f avfoundation -list_devices true -i ""`.

    Args:
        salida: texto de stderr de ffmpeg.

    Returns:
        Las cámaras de video, en el orden de AVFoundation (el mismo índice que usa OpenCV). Las
        pantallas ("Capture screen N") no son cámaras y se omiten.
    """
    camaras: list[Camara] = []
    en_video = False
    for linea in salida.splitlines():
        if "AVFoundation video devices" in linea:
            en_video = True
        elif "AVFoundation audio devices" in linea:
            break
        elif en_video:
            m = re.search(r"\[(\d+)\]\s+(.+?)\s*$", linea)
            if m and not m.group(2).lower().startswith("capture screen"):
                camaras.append(Camara(int(m.group(1)), m.group(2)))
    return camaras


def parsear_system_profiler(salida: str) -> list[Camara]:
    """Extrae las cámaras de `system_profiler SPCameraDataType -json` (sin índices reales:
    se numeran por orden, que suele coincidir con OpenCV pero no está garantizado)."""
    try:
        datos = json.loads(salida)
    except ValueError:
        return []
    return [Camara(i, c.get("_name", f"Cámara {i}")) for i, c in enumerate(datos.get("SPCameraDataType", []))]


def listar_camaras(ejecutar=subprocess.run) -> list[Camara]:
    """Lista las cámaras del Mac.

    Usa `ffmpeg -f avfoundation -list_devices` (da el índice exacto de OpenCV) y, si ffmpeg no
    está, `system_profiler SPCameraDataType`.

    Args:
        ejecutar: función tipo `subprocess.run` (para pruebas).

    Returns:
        Las cámaras encontradas; vacía si no hay herramientas o no hay cámaras.
    """
    if shutil.which("ffmpeg"):
        try:
            r = ejecutar(
                ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True, text=True, timeout=10,
            )
            camaras = parsear_ffmpeg(r.stderr)
            if camaras:
                return camaras
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("[Camara] ffmpeg no pudo listar: %s", error)
    if shutil.which("system_profiler"):
        try:
            r = ejecutar(["system_profiler", "SPCameraDataType", "-json"], capture_output=True, text=True, timeout=15)
            return parsear_system_profiler(r.stdout)
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("[Camara] system_profiler no pudo listar: %s", error)
    return []


def evaluar_fps(fps_medidos: float, fps_pedidos: int, huecos: int, frames: int) -> list[str]:
    """Avisos sobre los fps reales.

    Args:
        fps_medidos: fps efectivos de la captura.
        fps_pedidos: fps configurados.
        huecos: veces que pasó más de 1,5 periodos entre dos frames.
        frames: frames leídos.

    Returns:
        Lista de avisos (vacía si todo está bien): fps bajo lo configurado, bajo el mínimo
        de RNF-13, o frames perdidos.
    """
    avisos = []
    if frames and fps_medidos < fps_pedidos * 0.9:
        avisos.append(f"la cámara entrega {fps_medidos:.1f} fps, menos de los {fps_pedidos} configurados")
    if frames and fps_medidos < FPS_MIN * 0.9:
        avisos.append(f"{fps_medidos:.1f} fps no cumple el mínimo de {FPS_MIN} fps (RNF-13)")
    if huecos:
        avisos.append(f"se perdieron frames ({huecos} huecos entre frames)")
    return avisos
