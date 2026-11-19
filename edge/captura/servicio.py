"""Servicio de captura de tocados: cámara + lector Favero + recorte (EDGE01).

    python -m edge.captura.servicio --puerto '/dev/cu.usbmodem*' --camara 0

Con el simulador (`python -m edge.favero.simulador`) y un video pregrabado como cámara:

    python -m edge.captura.servicio --puerto <ruta del pty> --camara clip.mp4 --fuente simulado

Cada tocado deja `datos/edge/tocados/tocado_*.mp4` y `.json`. No envía nada a Fog: el envío
solo se hace con "Solicitar VAR" (D-04) y llega con EDGE02.
"""

from __future__ import annotations

import argparse
import logging
import time

from edge.captura.buffer import BufferCircular, memoria_estimada_mb
from edge.captura.config import ConfigCaptura
from edge.captura.fuente import HiloCaptura
from edge.captura.tocados import CapturaTocados, cargar_desfase_ms
from edge.favero.lector import BAUDIOS_USB, LectorFavero

logger = logging.getLogger(__name__)


def _fuente_video(texto: str) -> int | str:
    return int(texto) if texto.isdigit() else texto


def principal(argv: list[str] | None = None) -> int:
    """Arranca el servicio hasta Ctrl+C.

    Args:
        argv: argumentos (por defecto `sys.argv`).

    Returns:
        Código de salida: 0 al terminar con Ctrl+C, 1 si la cámara no abre.
    """
    parser = argparse.ArgumentParser(description="Captura de tocados Favero + cámara frontal.")
    parser.add_argument("--puerto", default="/dev/cu.usbmodem*", help="puerto del Arduino puente (admite *)")
    parser.add_argument("--baudios", type=int, default=BAUDIOS_USB, help="velocidad del lado USB del puente")
    parser.add_argument("--camara", default="0", help="índice de la cámara o ruta de un video pregrabado")
    parser.add_argument("--camara-id", default="frontal", help="nombre de la cámara (clave de la calibración)")
    parser.add_argument(
        "--fuente", choices=["favero", "simulado"], default="favero", help="origen que se anota en el JSON"
    )
    parser.add_argument("--ancho", type=int, default=1280)
    parser.add_argument("--alto", type=int, default=720)
    parser.add_argument("--pacear", action="store_true", help="con un archivo de video, avanzar a su ritmo real")
    parser.add_argument("--espera-arranque", type=float, default=2.0, help="segundos tras abrir el puerto serie")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = ConfigCaptura.desde_entorno()
    desfase = cargar_desfase_ms(config.archivo_latencia, args.camara_id)
    if desfase is None:
        logger.warning(
            "[Captura] Cámara '%s' sin calibrar: corrección de latencia = 0 (ver calibrar_latencia.py)", args.camara_id
        )
    logger.info(
        "[Captura] Buffer de %.1f s (~%.0f MB a %dx%d, %d fps)",
        config.capacidad_buffer_s,
        memoria_estimada_mb(config.capacidad_buffer_s, config.fps, args.ancho, args.alto),
        args.ancho,
        args.alto,
        config.fps,
    )

    buffer = BufferCircular(config.capacidad_buffer_s)
    camara = HiloCaptura(
        _fuente_video(args.camara),
        buffer,
        fps=config.fps,
        ancho=args.ancho,
        alto=args.alto,
        al_ritmo_del_archivo=args.pacear,
    )
    try:
        camara.iniciar()
    except RuntimeError as error:
        logger.error("[Captura] %s (en macOS: Ajustes > Privacidad > Cámara para la terminal)", error)
        return 1
    captura = CapturaTocados(buffer, config, camara_id=args.camara_id, fuente=args.fuente, desfase_ms=desfase)
    lector = LectorFavero(
        args.puerto, captura.registrar_flanco, baudios=args.baudios, espera_arranque_s=args.espera_arranque
    )
    captura.iniciar()
    lector.iniciar()
    try:
        while True:
            time.sleep(10)
            logger.info(
                "[Captura] fps cámara %.1f · lector %s · tocados %d",
                camara.fps_medidos,
                lector.estado(),
                captura.tocados_escritos,
            )
    except KeyboardInterrupt:
        pass
    finally:
        lector.detener()
        captura.detener()
        camara.detener()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
