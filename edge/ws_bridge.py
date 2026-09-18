"""Edge — bridge RTSP -> WebSocket.

Pipeline: iPhone (Larix, RTMP) -> MediaMTX (RTSP) -> [este servicio] ->
WebSocket -> frontend React Native.

Lee dos streams RTSP (uno por cámara) y redistribuye cada frame como JPEG
a los clientes WebSocket conectados a esa cámara (ws://host:PORT/<camera>).
No hace pose/features/inferencia — eso es fog/; esto solo redistribuye
video para preview en vivo.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import websockets
from websockets import WebSocketServerProtocol

from capture import CameraCapture

logger = logging.getLogger(__name__)

RTSP_URLS: dict[str, str] = {
    "front": os.environ["RTSP_FRONT_URL"],
    "top": os.environ["RTSP_TOP_URL"],
}
WS_PORT = int(os.environ.get("WS_PORT", "8001"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "70"))
TARGET_FPS = int(os.environ.get("TARGET_FPS", "15"))

# Registry de clientes WebSocket por cámara.
_clients: dict[str, set[WebSocketServerProtocol]] = {name: set() for name in RTSP_URLS}


async def handle_connection(ws: WebSocketServerProtocol, path: str) -> None:
    camera = path.strip("/")
    if camera not in _clients:
        await ws.close(code=1008, reason=f"cámara desconocida: {camera!r}")
        return

    clients = _clients[camera]
    clients.add(ws)
    logger.info("[Edge][%s] Cliente conectado — total: %d", camera, len(clients))
    try:
        await ws.wait_closed()
    finally:
        clients.discard(ws)
        logger.info("[Edge][%s] Cliente desconectado — total: %d", camera, len(clients))


async def _broadcast(camera: str, frame: bytes) -> None:
    clients = _clients[camera]
    if not clients:
        return

    recipients = list(clients)
    results = await asyncio.gather(
        *(ws.send(frame) for ws in recipients), return_exceptions=True
    )
    for ws, result in zip(recipients, results):
        if isinstance(result, BaseException):
            clients.discard(ws)


async def stream_loop(camera: str, rtsp_url: str, executor: ThreadPoolExecutor) -> None:
    """Lee frames de una cámara a TARGET_FPS y los difunde a sus clientes.
    Sigue leyendo aunque no haya clientes conectados, para no dejar que
    MediaMTX acumule buffer esperando un consumidor."""
    logger.info("[Edge][%s] Conectando a %s", camera, rtsp_url)
    capture = CameraCapture(camera, rtsp_url, JPEG_QUALITY)
    loop = asyncio.get_running_loop()
    interval = 1.0 / TARGET_FPS

    while True:
        start = loop.time()

        frame = await loop.run_in_executor(executor, capture.read_frame)
        if frame is not None:
            await _broadcast(camera, frame)

        elapsed = loop.time() - start
        await asyncio.sleep(max(0.0, interval - elapsed))


async def main() -> None:
    logger.info("[Edge] WS escuchando en ws://0.0.0.0:%d", WS_PORT)

    executor = ThreadPoolExecutor(max_workers=len(RTSP_URLS))
    streams = [
        asyncio.create_task(stream_loop(camera, url, executor))
        for camera, url in RTSP_URLS.items()
    ]

    async with websockets.serve(handle_connection, "0.0.0.0", WS_PORT):
        await asyncio.gather(*streams)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(main())
