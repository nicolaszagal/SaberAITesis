"""Pruebas de las rutas WebSocket de Edge (DEF-11): `/front`, `/top` y los alias
`/ws/camera/front`, `/ws/camera/top`. Usan un WebSocket falso, sin cámaras."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_EDGE_DIR = str(Path(__file__).resolve().parents[2] / "edge")


class FakeWebSocket:
    """WebSocket mínimo: registra si se cerró y devuelve de inmediato en wait_closed."""

    def __init__(self) -> None:
        self.closed_with: tuple[int, str] | None = None
        self.was_registered = False

    async def wait_closed(self) -> None:
        self.was_registered = any(self in c for c in ws_bridge._clients.values())

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = (code, reason)


@pytest.fixture(autouse=True)
def ws_bridge_module(monkeypatch):
    global ws_bridge
    monkeypatch.setenv("RTSP_FRONT_URL", "rtsp://falso/front")
    monkeypatch.setenv("RTSP_TOP_URL", "rtsp://falso/top")
    monkeypatch.setenv("WS_PORT", "8002")
    monkeypatch.syspath_prepend(_EDGE_DIR)
    sys.modules.pop("ws_bridge", None)
    ws_bridge = importlib.import_module("ws_bridge")
    yield
    sys.modules.pop("ws_bridge", None)


@pytest.mark.parametrize(
    "path,camera",
    [
        ("/front", "front"),
        ("/top", "top"),
        ("/ws/camera/front", "front"),
        ("/ws/camera/top", "top"),
    ],
)
async def test_ruta_valida_registra_cliente_y_lo_libera(path, camera):
    ws = FakeWebSocket()

    await ws_bridge.handle_connection(ws, path)

    assert ws.was_registered is True
    assert ws.closed_with is None
    assert ws not in ws_bridge._clients[camera]


@pytest.mark.parametrize("path", ["/", "/side", "/ws/camera/side", "/ws/camera"])
async def test_ruta_desconocida_cierra_con_1008(path):
    ws = FakeWebSocket()

    await ws_bridge.handle_connection(ws, path)

    assert ws.closed_with is not None and ws.closed_with[0] == 1008
    assert ws.was_registered is False


def test_puerto_por_defecto_es_8002(monkeypatch):
    monkeypatch.delenv("WS_PORT")
    sys.modules.pop("ws_bridge", None)
    assert importlib.import_module("ws_bridge").WS_PORT == 8002
