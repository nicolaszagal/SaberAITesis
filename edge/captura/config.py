"""Parámetros de la captura del clip (EDGE01). Se leen del entorno para poder ajustarlos."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Ventana del clip alrededor del tocado. Valores de EDGE02 (decisión del autor, 18/11/2026):
# 2,0 s antes y 0,5 s después. DEF-32 sigue abierto en contexto_sabre.md y EDGE02 los moverá a
# shared/config.py para que Fog use los mismos; hasta entonces son parámetros de Edge.
VENTANA_PRE_MS_DEFECTO = 2000
VENTANA_POST_MS_DEFECTO = 500

CAPACIDAD_MIN_S = 5.0  # RF-04: al menos 5 s de buffer
FPS_MIN = 30  # RNF-13
ALTO_MIN = 720  # RNF-13


@dataclass(frozen=True)
class ConfigCaptura:
    """Parámetros de captura.

    Attributes:
        pre_ms: milisegundos del clip antes del tocado.
        post_ms: milisegundos del clip después del tocado (también agrupa la 2.ª luz de un doble).
        fps: cuadros por segundo del clip y de la cámara.
        k_tocados: cuántos tocados se conservan en disco.
        directorio: carpeta de los clips y sus JSON.
        directorio_calibracion: carpeta del archivo de latencia por cámara.
    """

    pre_ms: int = VENTANA_PRE_MS_DEFECTO
    post_ms: int = VENTANA_POST_MS_DEFECTO
    fps: int = FPS_MIN
    k_tocados: int = 10
    directorio: Path = Path("datos/edge/tocados")
    archivo_latencia: Path = Path("datos/edge/latencia_camara.json")

    @property
    def capacidad_buffer_s(self) -> float:
        """Capacidad del buffer: al menos 5 s (RF-04) y siempre la ventana previa más la posterior."""
        return max(CAPACIDAD_MIN_S, self.pre_ms / 1000) + self.post_ms / 1000

    @classmethod
    def desde_entorno(cls) -> "ConfigCaptura":
        """Lee `EDGE_VENTANA_PRE_MS`, `EDGE_VENTANA_POST_MS`, `EDGE_FPS`, `EDGE_K_TOCADOS`,
        `EDGE_DIR_TOCADOS` y `EDGE_ARCHIVO_LATENCIA`; lo que falte usa el valor por defecto."""
        env = os.environ
        return cls(
            pre_ms=int(env.get("EDGE_VENTANA_PRE_MS", VENTANA_PRE_MS_DEFECTO)),
            post_ms=int(env.get("EDGE_VENTANA_POST_MS", VENTANA_POST_MS_DEFECTO)),
            fps=int(env.get("EDGE_FPS", FPS_MIN)),
            k_tocados=int(env.get("EDGE_K_TOCADOS", 10)),
            directorio=Path(env.get("EDGE_DIR_TOCADOS", "datos/edge/tocados")),
            archivo_latencia=Path(env.get("EDGE_ARCHIVO_LATENCIA", "datos/edge/latencia_camara.json")),
        )
