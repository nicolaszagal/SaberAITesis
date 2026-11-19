"""Logs de tiempo para la prueba de carga ESTRES01.

Solo escriben una línea de log por etapa cuando el entorno tiene ``ESTRES_TIEMPOS=1``. No cambian la
lógica de ningún nodo: sin la variable, ``activo()`` es falso y nada se mide ni se registra.
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger("estres.tiempos")


def activo() -> bool:
    """Indica si la medición de tiempos de ESTRES01 está encendida.

    Returns:
        True si ``ESTRES_TIEMPOS`` vale ``"1"`` en el entorno del proceso.
    """
    return os.environ.get("ESTRES_TIEMPOS") == "1"


def registrar(etapa: str, **campos: object) -> None:
    """Escribe ``ESTRES_TIEMPOS etapa=<etapa> k=v ...`` si la medición está encendida.

    Args:
        etapa: nombre de la etapa medida (``clip``, ``features``, ``espera_cloud``).
        **campos: pares clave-valor; los ``float`` se escriben con tres decimales.
    """
    if not activo():
        return
    partes = " ".join(
        f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in campos.items()
    )
    _log.info("ESTRES_TIEMPOS etapa=%s %s", etapa, partes)
