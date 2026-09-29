"""Configuración del log técnico de Fog y Cloud.

El log técnico (un mensaje INFO por evento relevante: clip recibido,
features extraídas, veredicto, error) es independiente del log de evidencia
(`sabre.evidencia`, ver fog/infrastructure/evidencia/).
"""

import logging

from shared import config

FORMATO = "%(asctime)s %(levelname)s:%(name)s:%(message)s"

# Librerías cuyo detalle interno no es un evento del sistema.
LIBRERIAS_EN_WARNING = ("aioice", "aiortc", "uvicorn.access", "ultralytics")


def configurar_logging_tecnico(nivel: str | None = None) -> None:
    """Configura el log técnico y baja las librerías ruidosas a WARNING.

    Args:
        nivel: nivel del log del sistema (`INFO`, `DEBUG`, ...). Si es None
            usa `config.LOG_LEVEL` (INFO por defecto).

    Raises:
        ValueError: si el nivel no es un nombre de nivel de `logging`.
    """
    nivel = (nivel or config.LOG_LEVEL).upper()
    if not isinstance(logging.getLevelName(nivel), int):
        raise ValueError(f"LOG_LEVEL desconocido: {nivel!r}")
    logging.basicConfig(level=nivel, format=FORMATO)
    logging.getLogger().setLevel(nivel)
    for nombre in LIBRERIAS_EN_WARNING:
        logging.getLogger(nombre).setLevel(logging.WARNING)
