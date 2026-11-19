"""Núcleo de Edge (EDGE02): cámara, buffer, tocados, envío a Fog y señal de prueba.

Junta las piezas de EDGE01 y EDGE02 detrás de una sola interfaz que usa la API local. Todo lo
que viene después de un evento de tocado es idéntico para sus dos fuentes: el lector Favero y la
señal de prueba entran por `CapturaTocados.registrar_flanco`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from edge.captura.buffer import BufferCircular
from edge.captura.camara import Camara, evaluar_fps, listar_camaras
from edge.captura.config import ConfigCaptura
from edge.captura.config_edge import ConfigEdge, cargar, guardar
from edge.captura.envio import EnvioFog
from edge.captura.fuente import HiloCaptura
from edge.captura.tocados import CapturaTocados, cargar_desfase_ms
from edge.favero.lector import Flanco, LectorFavero

logger = logging.getLogger(__name__)


class NucleoEdge:
    """Estado y operaciones de Edge."""

    def __init__(
        self,
        captura_cfg: ConfigCaptura,
        archivo_config: Path,
        *,
        camara_id: str = "frontal",
        modo_prueba: bool = False,
        fuente_video: str | None = None,
        lector: LectorFavero | None = None,
        envio: EnvioFog | None = None,
        listar: Callable[[], list[Camara]] = listar_camaras,
        reloj_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        """Arma el núcleo (no abre la cámara hasta `iniciar`).

        Args:
            captura_cfg: ventana, K y carpetas.
            archivo_config: `datos/edge/config.json` (cámara, resolución, fps).
            camara_id: nombre de la cámara (clave de la calibración).
            modo_prueba: si existe la señal de prueba (`MODO_PRUEBA_SENAL=1`).
            fuente_video: ruta de un video que hace de cámara (pruebas y demostración).
            lector: lector Favero ya creado con `nucleo.registrar_flanco`, o `None` sin cable.
            envio: envío automático a Fog, o `None` para no enviar.
            listar: función que lista cámaras (para pruebas).
            reloj_ns: reloj monótono de los frames y de la señal de prueba.
        """
        self._captura_cfg = captura_cfg
        self._archivo_config = archivo_config
        self._camara_id = camara_id
        self.modo_prueba = modo_prueba
        self._fuente_video = fuente_video
        self.lector = lector
        self.envio = envio
        self._listar = listar
        self._reloj_ns = reloj_ns
        self._lock = threading.Lock()
        self.config = cargar(archivo_config)
        self.buffer = BufferCircular(captura_cfg.capacidad_buffer_s)
        self.captura = CapturaTocados(
            self.buffer, captura_cfg, camara_id=camara_id, fuente="favero",
            desfase_ms=cargar_desfase_ms(captura_cfg.archivo_latencia, camara_id),
            al_tocado=envio.encolar if envio else None, enviar=envio is not None, reloj_ns=reloj_ns,
        )
        self._camara: HiloCaptura | None = None
        self.error_camara: str | None = None

    def registrar_flanco(self, flanco: Flanco) -> None:
        """Entrada única de los eventos de tocado (la usa el lector Favero)."""
        self.captura.registrar_flanco(flanco)

    # ---- ciclo de vida

    def iniciar(self) -> None:
        """Abre la cámara y arranca los hilos de captura, lector y envío.

        Una cámara que no abre no impide arrancar: el error queda en `estado()` y se puede
        corregir con `PUT /config`.
        """
        self._abrir_camara()
        self.captura.iniciar()
        if self.lector is not None:
            self.lector.iniciar()
        if self.envio is not None:
            self.envio.iniciar()

    def detener(self) -> None:
        """Detiene todos los hilos."""
        if self.lector is not None:
            self.lector.detener()
        if self.envio is not None:
            self.envio.detener()
        self.captura.detener()
        self._cerrar_camara()

    def _abrir_camara(self) -> None:
        cfg = self.config
        self.buffer.vaciar()
        fuente: int | str = self._fuente_video if self._fuente_video else cfg.camara_indice
        camara = HiloCaptura(
            fuente, self.buffer, fps=cfg.fps, ancho=cfg.ancho, alto=cfg.alto,
            al_ritmo_del_archivo=self._fuente_video is not None, reloj_ns=self._reloj_ns,
        )
        try:
            camara.iniciar()
            self.error_camara = None
        except RuntimeError as error:
            self.error_camara = f"{error} (en macOS: Ajustes > Privacidad y seguridad > Cámara)"
            logger.error("[Edge] %s", self.error_camara)
            camara = None
        self._camara = camara

    def _cerrar_camara(self) -> None:
        if self._camara is not None:
            self._camara.detener()
            self._camara = None

    # ---- operaciones de la API

    def camaras(self) -> list[dict[str, Any]]:
        """Dispositivos de video disponibles."""
        return [asdict(c) for c in self._listar()]

    def cambiar_config(self, nueva: ConfigEdge) -> ConfigEdge:
        """Valida, guarda y reabre la cámara con la nueva configuración.

        Raises:
            ConfigInvalida: si no cumple RNF-13 (no cambia nada).
        """
        guardar(self._archivo_config, nueva)
        with self._lock:
            self.config = nueva
            self._cerrar_camara()
            self._abrir_camara()
        return nueva

    def senal_prueba(self, luz_a: bool, luz_b: bool) -> dict[str, Any]:
        """Emite un tocado de prueba (`fuente='simulado'`, origen 'boton').

        Args:
            luz_a: enciende la luz de A (roja).
            luz_b: enciende la luz de B (verde); con ambas es un doble.

        Returns:
            Las luces emitidas.

        Raises:
            ValueError: si no se enciende ninguna luz.
            PermissionError: si el modo de prueba está apagado.
        """
        if not self.modo_prueba:
            raise PermissionError("MODO_PRUEBA_SENAL no está activo")
        if not (luz_a or luz_b):
            raise ValueError("se requiere al menos una luz")
        t = self._reloj_ns()
        if luz_a:
            self.registrar_flanco(Flanco("A", "ROJA", t, "simulado", "boton"))
        if luz_b:
            self.registrar_flanco(Flanco("B", "VERDE", t, "simulado", "boton"))
        logger.info("[Edge] Señal de prueba (botón): luz_a=%s luz_b=%s, fuente=simulado", luz_a, luz_b)
        return {"luz_a": luz_a, "luz_b": luz_b, "fuente": "simulado", "origen": "boton"}

    def preview_jpeg(self) -> bytes | None:
        """Un cuadro de la cámara en JPEG para encuadrar, o `None` si no hay frames."""
        import cv2

        ultimo = self.buffer.ultimo()
        if ultimo is None:
            return None
        ok, jpg = cv2.imencode(".jpg", ultimo.imagen, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        return jpg.tobytes() if ok else None

    def tocados(self) -> list[dict[str, Any]]:
        """Los últimos K tocados en disco, el más reciente primero, con su estado de envío."""
        import json

        salida = []
        for ruta in sorted(self._captura_cfg.directorio.glob("tocado_*.json"), reverse=True):
            try:
                salida.append(json.loads(ruta.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return salida

    def estado(self) -> dict[str, Any]:
        """Instantánea para `GET /estado`: cámara, fps reales, señal y modo de prueba."""
        cam = self._camara
        cfg = self.config
        fps_medidos = cam.fps_medidos if cam else 0.0
        estado_lector = self.lector.estado() if self.lector else None
        return {
            "camara": {
                "abierta": cam is not None and cam.error is None,
                "error": self.error_camara or (cam.error if cam else None),
                "indice": cfg.camara_indice,
                "resolucion": {"ancho": cam.ancho if cam and cam.ancho else cfg.ancho,
                               "alto": cam.alto if cam and cam.alto else cfg.alto},
                "fps_configurados": cfg.fps,
                "fps_medidos": round(fps_medidos, 1),
                "avisos": evaluar_fps(fps_medidos, cfg.fps, cam.huecos if cam else 0,
                                      cam.frames_leidos if cam else 0) if cam else [],
            },
            "senal": {
                "fuente": "favero" if self.lector else "ninguna",
                "sin_senal_favero": bool(self.lector) and estado_lector.get("senal") is not True,
                "lector": estado_lector,
            },
            "modo_prueba": self.modo_prueba,
            "tocados_escritos": self.captura.tocados_escritos,
            "envio": None if self.envio is None else {
                "enviados": self.envio.enviados,
                "pendientes": len(self.envio.pendientes()),
                "errores": self.envio.errores_definitivos,
            },
            "camara_id": self._camara_id,
            "ventana": {"pre_ms": self._captura_cfg.pre_ms, "post_ms": self._captura_cfg.post_ms},
        }
