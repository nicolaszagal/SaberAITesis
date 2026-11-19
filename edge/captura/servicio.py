"""Servicio de Edge: cámara, señal Favero (o señal de prueba), clip por tocado, envío a Fog y API local.

    python -m edge.captura.servicio --puerto '/dev/cu.usbmodem*'      # con el aparato
    MODO_PRUEBA_SENAL=1 python -m edge.captura.servicio --sin-lector  # sin cable: botón de prueba

Con un video pregrabado como cámara: `--camara-video clip.mp4`. Cada tocado deja
`datos/edge/tocados/tocado_*.mp4` y `.json` y se sube solo a Fog (preproceso, sin abrir la
revisión: la revisión VAR se abre con "Solicitar VAR" en el frontend, D-04).
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from edge.api_local import ApiLocal
from edge.captura.buffer import memoria_estimada_mb
from edge.captura.config import ConfigCaptura
from edge.captura.envio import EnvioFog, credenciales_desde_entorno
from edge.captura.nucleo import NucleoEdge
from edge.favero.lector import BAUDIOS_USB, LectorFavero

logger = logging.getLogger(__name__)

ARCHIVO_CONFIG = Path("datos/edge/config.json")


def principal(argv: list[str] | None = None) -> int:
    """Arranca Edge hasta Ctrl+C.

    Args:
        argv: argumentos (por defecto `sys.argv`).

    Returns:
        0 al terminar con Ctrl+C.
    """
    parser = argparse.ArgumentParser(description="Edge: captura de tocados.")
    parser.add_argument("--puerto", default="/dev/cu.usbmodem*", help="puerto del Arduino puente (admite *)")
    parser.add_argument("--baudios", type=int, default=BAUDIOS_USB, help="velocidad del lado USB del puente")
    parser.add_argument("--sin-lector", action="store_true", help="no abrir el puerto serie (sin cable)")
    parser.add_argument("--camara-id", default="frontal", help="nombre de la cámara (clave de la calibración)")
    parser.add_argument("--camara-video", default=None, help="ruta de un video que hace de cámara")
    parser.add_argument("--fog-url", default=os.environ.get("FOG_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--sin-envio", action="store_true", help="no subir los tocados a Fog")
    parser.add_argument("--puerto-api", type=int, default=8765, help="puerto de la API local (127.0.0.1)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = ConfigCaptura.desde_entorno()
    envio = None if args.sin_envio else EnvioFog(cfg.directorio, args.fog_url, credenciales_desde_entorno())
    nucleo = NucleoEdge(
        cfg, ARCHIVO_CONFIG, camara_id=args.camara_id, modo_prueba=os.environ.get("MODO_PRUEBA_SENAL") == "1",
        fuente_video=args.camara_video, envio=envio,
    )
    if not args.sin_lector:
        nucleo.lector = LectorFavero(args.puerto, nucleo.registrar_flanco, baudios=args.baudios)
    logger.info(
        "[Edge] Buffer de %.1f s (~%.0f MB a %dx%d, %d fps)", cfg.capacidad_buffer_s,
        memoria_estimada_mb(cfg.capacidad_buffer_s, nucleo.config.fps, nucleo.config.ancho, nucleo.config.alto),
        nucleo.config.ancho, nucleo.config.alto, nucleo.config.fps,
    )
    if nucleo.modo_prueba:
        logger.warning("[Edge] MODO_PRUEBA_SENAL=1: los tocados del botón quedan como fuente 'simulado'")
    api = ApiLocal(nucleo, args.puerto_api)
    nucleo.iniciar()
    api.iniciar()
    logger.info("[Edge] API local en http://127.0.0.1:%d", api.puerto)
    try:
        while True:
            time.sleep(10)
            e = nucleo.estado()
            logger.info("[Edge] fps %.1f · señal %s · tocados %d · envío %s",
                        e["camara"]["fps_medidos"], e["senal"]["fuente"], e["tocados_escritos"], e["envio"])
    except KeyboardInterrupt:
        pass
    finally:
        api.detener()
        nucleo.detener()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
