"""`/edge/*`: Fog reenvía a Edge, en el mismo equipo por 127.0.0.1, la configuración de cámara, el
estado y la señal de prueba (EDGE02). El navegador solo habla con Fog (JWT), nunca con Edge, así
que funciona igual desde el frontend local y desde el desplegado.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from fog.infrastructure.api.errores import ErrorConCodigo
from fog.infrastructure.api.seguridad import exigir_autenticacion
from shared import config

router = APIRouter(prefix="/edge", tags=["edge"], dependencies=[Depends(exigir_autenticacion)])

TIMEOUT_S = 5.0


def _llamar(metodo: str, ruta: str, cuerpo: bytes | None) -> tuple[int, bytes, str]:
    req = urllib.request.Request(
        config.EDGE_URL.rstrip("/") + ruta, data=cuerpo, method=metodo,
        headers={"Content-Type": "application/json"} if cuerpo is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers.get("Content-Type", "application/json")


async def _reenviar(metodo: str, ruta: str, cuerpo: bytes | None = None) -> Response:
    try:
        estado, datos, tipo = await asyncio.to_thread(_llamar, metodo, ruta, cuerpo)
    except (OSError, urllib.error.URLError) as exc:
        raise ErrorConCodigo(503, f"Edge no responde ({exc})", "edge_no_disponible") from exc
    return Response(content=datos, status_code=estado, media_type=tipo)


@router.get("/camaras", summary="Cámaras de video del equipo de Edge")
async def camaras() -> Response:
    return await _reenviar("GET", "/camaras")


@router.get("/config", summary="Configuración de cámara de Edge (dispositivo, resolución, fps)")
async def leer_config() -> Response:
    return await _reenviar("GET", "/config")


@router.put("/config", summary="Cambia la cámara, la resolución y los fps (≥ 720p y ≥ 30 fps, RNF-13)")
async def escribir_config(request: Request) -> Response:
    return await _reenviar("PUT", "/config", await request.body())


@router.get("/estado", summary="Estado de Edge: cámara, fps reales, señal Favero y modo de prueba")
async def estado() -> Response:
    return await _reenviar("GET", "/estado")


@router.get("/preview", summary="Un cuadro de la cámara (JPEG) para encuadrar; no es video en vivo")
async def preview() -> Response:
    return await _reenviar("GET", "/preview.jpg")


@router.post(
    "/senal-prueba",
    summary="Emite una señal de prueba (botón temporal); solo con MODO_PRUEBA_SENAL=1",
    description=(
        "Cuerpo `{luz_a, luz_b}`. El tocado queda con `fuente='simulado'` y origen 'boton': no "
        "cuenta como Validación 2. Sin `MODO_PRUEBA_SENAL=1` la ruta no existe (404)."
    ),
)
async def senal_prueba(request: Request) -> Response:
    if not config.MODO_PRUEBA_SENAL:
        raise HTTPException(404, "Not Found")
    return await _reenviar("POST", "/senal-prueba", await request.body())
