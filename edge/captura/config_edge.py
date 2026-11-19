"""Configuración de Edge guardada en `datos/edge/config.json` (EDGE02): cámara, resolución y fps."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from edge.captura.camara import ALTO_MIN, FPS_MIN


class ConfigInvalida(ValueError):
    """Valores que no cumplen RNF-13 (≥ 720p y ≥ 30 fps) o están fuera de rango."""


@dataclass(frozen=True)
class ConfigEdge:
    """Cámara que graba el combate.

    Attributes:
        camara_indice: índice de OpenCV (de `GET /camaras`).
        ancho: ancho pedido a la cámara.
        alto: alto pedido (≥ 720).
        fps: cuadros por segundo pedidos (≥ 30).
    """

    camara_indice: int = 0
    ancho: int = 1280
    alto: int = 720
    fps: int = 30

    def validar(self) -> None:
        """Comprueba rangos y RNF-13.

        Raises:
            ConfigInvalida: si el alto es menor a 720, los fps menores a 30 o hay valores no válidos.
        """
        if self.camara_indice < 0:
            raise ConfigInvalida("camara_indice no puede ser negativo")
        if self.alto < ALTO_MIN or self.ancho < self.alto:
            raise ConfigInvalida(f"la resolución debe ser al menos {ALTO_MIN}p (RNF-13) y apaisada")
        if not FPS_MIN <= self.fps <= 120:
            raise ConfigInvalida(f"los fps deben estar entre {FPS_MIN} (RNF-13) y 120")


def cargar(ruta: Path) -> ConfigEdge:
    """Lee la configuración; si no existe o está dañada, devuelve la de fábrica."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        cfg = ConfigEdge(**{k: int(datos[k]) for k in ("camara_indice", "ancho", "alto", "fps") if k in datos})
        cfg.validar()
        return cfg
    except (OSError, ValueError, TypeError):
        return ConfigEdge()


def guardar(ruta: Path, cfg: ConfigEdge) -> None:
    """Valida y guarda la configuración de forma atómica.

    Raises:
        ConfigInvalida: si no es válida (no se escribe nada).
    """
    cfg.validar()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
    os.replace(tmp, ruta)
