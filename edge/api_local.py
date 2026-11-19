"""API local de Edge (EDGE02): escucha SOLO en 127.0.0.1; solo Fog le habla.

    GET  /camaras        cámaras de video del equipo
    GET  /config         cámara, resolución y fps
    PUT  /config         cambia la configuración (≥ 720p y ≥ 30 fps, RNF-13); 422 si no cumple
    GET  /estado         cámara, fps reales, fuente de señal y modo de prueba
    GET  /tocados        últimos K tocados con su estado de envío
    GET  /preview.jpg    un cuadro de la cámara (no es video en vivo)
    POST /senal-prueba   {luz_a, luz_b}; existe SOLO con MODO_PRUEBA_SENAL=1 (si no, 404)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from edge.captura.config_edge import ConfigEdge, ConfigInvalida
from edge.captura.nucleo import NucleoEdge

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"


def _manejador(nucleo: NucleoEdge) -> type[BaseHTTPRequestHandler]:
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, formato: str, *args: Any) -> None:  # silencia el log por petición
            logger.debug(formato, *args)

        def _responder(self, estado: int, cuerpo: Any, tipo: str = "application/json") -> None:
            datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo, ensure_ascii=False).encode()
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def _json(self) -> dict[str, Any]:
            largo = int(self.headers.get("Content-Length") or 0)
            datos = json.loads(self.rfile.read(largo) or b"{}")
            if not isinstance(datos, dict):
                raise ValueError("se esperaba un objeto JSON")
            return datos

        def do_GET(self) -> None:  # noqa: N802
            ruta = self.path.split("?")[0]
            if ruta == "/camaras":
                self._responder(200, nucleo.camaras())
            elif ruta == "/config":
                self._responder(200, asdict(nucleo.config))
            elif ruta == "/estado":
                self._responder(200, nucleo.estado())
            elif ruta == "/tocados":
                self._responder(200, nucleo.tocados())
            elif ruta == "/preview.jpg":
                jpg = nucleo.preview_jpeg()
                if jpg is None:
                    self._responder(404, {"detail": "todavía no hay frames"})
                else:
                    self._responder(200, jpg, "image/jpeg")
            else:
                self._responder(404, {"detail": "Not Found"})

        def do_PUT(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/config":
                self._responder(404, {"detail": "Not Found"})
                return
            try:
                actual = asdict(nucleo.config)
                actual.update({k: int(v) for k, v in self._json().items() if k in actual})
                nuevo = nucleo.cambiar_config(ConfigEdge(**actual))
            except (ValueError, TypeError, ConfigInvalida) as error:
                self._responder(422, {"detail": str(error)})
                return
            self._responder(200, asdict(nuevo))

        def do_POST(self) -> None:  # noqa: N802
            # Con el modo de prueba apagado la ruta no existe: 404, no 403.
            if self.path.split("?")[0] != "/senal-prueba" or not nucleo.modo_prueba:
                self._responder(404, {"detail": "Not Found"})
                return
            try:
                cuerpo = self._json()
                r = nucleo.senal_prueba(bool(cuerpo.get("luz_a")), bool(cuerpo.get("luz_b")))
            except (ValueError, json.JSONDecodeError) as error:
                self._responder(422, {"detail": str(error)})
                return
            self._responder(200, r)

    return Manejador


class ApiLocal:
    """Servidor HTTP en 127.0.0.1 que corre en un hilo."""

    def __init__(self, nucleo: NucleoEdge, puerto: int = 8765, host: str = HOST) -> None:
        """Crea el servidor (no escucha hasta `iniciar`).

        Args:
            nucleo: operaciones de Edge.
            puerto: puerto TCP (0 = uno libre, para pruebas).
            host: debe ser de loopback; Edge nunca escucha hacia afuera.

        Raises:
            ValueError: si `host` no es de loopback.
        """
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("la API local de Edge solo puede escuchar en 127.0.0.1")
        self._servidor = ThreadingHTTPServer((host, puerto), _manejador(nucleo))
        self._hilo: Any = None

    @property
    def puerto(self) -> int:
        """Puerto en el que escucha."""
        return self._servidor.server_address[1]

    def iniciar(self) -> None:
        """Arranca el servidor en un hilo."""
        import threading

        self._hilo = threading.Thread(target=self._servidor.serve_forever, name="api-local-edge", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        """Detiene el servidor."""
        self._servidor.shutdown()
        self._servidor.server_close()
