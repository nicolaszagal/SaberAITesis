"""Autenticación de las rutas de Fog y middleware de endurecimiento (DEPLOY05).

- `exigir_autenticacion`: dependencia de router; exige `Authorization: Bearer`.
- `ip_cliente`: IP real, tomando `X-Forwarded-For` solo si viene del proxy de confianza.
- `EncabezadosSeguridad` y `TokenDeProxy`: middleware ASGI puro.
"""

from __future__ import annotations

import hmac

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, WebSocketException
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fog.application.autenticar import ValidarToken
from fog.composition import Container
from fog.domain.errors import TokenInvalido
from shared import config


def ip_cliente(conexion: HTTPConnection) -> str:
    """IP del cliente para el registro y el bloqueo por intentos.

    Args:
        conexion: petición HTTP o WebSocket.

    Returns:
        La entrada de `X-Forwarded-For` que corresponde al cliente según
        `PROXY_SALTOS_CONFIANZA` (la última con 1 salto; la penúltima con 2,
        cuando el túnel añade la IP de salida del proxy), solo si hay
        `PROXY_SHARED_TOKEN` configurado, es decir, si la petición ya pasó por
        el proxy de confianza; en otro caso la IP del socket.
    """
    if getattr(conexion.app.state, "proxy_token", None):
        entradas = [e.strip() for e in conexion.headers.get("x-forwarded-for", "").split(",")]
        saltos = max(config.PROXY_SALTOS_CONFIANZA, 1)
        if len(entradas) >= saltos and entradas[-saltos]:
            return entradas[-saltos]
    return conexion.client.host if conexion.client else "desconocida"


def _token_de(conexion: HTTPConnection) -> str | None:
    esquema, _, valor = conexion.headers.get("authorization", "").partition(" ")
    if esquema.lower() == "bearer" and valor.strip():
        return valor.strip()
    if conexion.scope["type"] == "websocket":
        # El navegador no puede enviar cabeceras en un WebSocket.
        return conexion.query_params.get("token")
    return None


@inject
async def exigir_autenticacion(
    conexion: HTTPConnection,
    validar: ValidarToken = Depends(Provide[Container.validar_token]),
) -> str:
    """Dependencia de router: exige un token válido.

    Args:
        conexion: petición HTTP o WebSocket.
        validar: caso de uso de validación de tokens.

    Returns:
        El usuario autenticado.

    Raises:
        HTTPException: 401 si el token falta o es inválido (HTTP).
        WebSocketException: código 1008 en el mismo caso (WebSocket).
    """
    try:
        return validar.execute(_token_de(conexion), ip_cliente(conexion))
    except TokenInvalido:
        if conexion.scope["type"] == "websocket":
            raise WebSocketException(code=1008) from None
        raise HTTPException(
            status_code=401,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


class EncabezadosSeguridad:
    """Agrega las cabeceras de seguridad a toda respuesta HTTP.

    `Cache-Control: no-store` va en todas las respuestas: la API no sirve
    contenido cacheable y así cubre `/auth/*` y los datos de revisión.
    """

    _FIJOS = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cache-control", b"no-store"),
    )

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                nombres = {n for n, _ in self._FIJOS}
                cabeceras = [
                    (n, v) for n, v in mensaje["headers"] if n.lower() not in nombres
                ]
                mensaje = {**mensaje, "headers": cabeceras + list(self._FIJOS)}
            await send(mensaje)

        await self.app(scope, receive, enviar)


class TokenDeProxy:
    """Rechaza con 403 toda petición sin el `X-Proxy-Token` esperado.

    Con `token=None` no hace nada (uso local).
    """

    def __init__(self, app: ASGIApp, token: str | None):
        self.app = app
        self._token = token.encode() if token else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._token is None or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        recibido = dict(scope["headers"]).get(b"x-proxy-token", b"")
        if hmac.compare_digest(recibido, self._token):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        respuesta = JSONResponse({"detail": "Acceso denegado"}, status_code=403)
        await respuesta(scope, receive, send)
