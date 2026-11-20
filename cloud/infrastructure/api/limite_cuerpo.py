"""Middleware ASGI que corta con 413 los cuerpos que superan el máximo.

Mira `Content-Length` y, si no viene (o miente), cuenta los bytes a medida que llegan: nunca
acumula más de `maximo` bytes en memoria.
"""

from __future__ import annotations

import json


class LimiteCuerpo:
    def __init__(self, app, maximo_bytes: int):
        self.app = app
        self.maximo = maximo_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declarado = dict(scope["headers"]).get(b"content-length")
        if declarado is not None and declarado.isdigit() and int(declarado) > self.maximo:
            await self._rechazar(send)
            return

        recibidos = 0
        excedido = False
        respondido = False

        async def receive_limitado():
            nonlocal recibidos, excedido
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                recibidos += len(mensaje.get("body", b""))
                if recibidos > self.maximo:
                    excedido = True
                    # Entrega un cuerpo vacío y terminado: la aplicación responderá 4xx por su
                    # cuenta, pero `send_limitado` lo reemplaza por el 413.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return mensaje

        async def send_limitado(mensaje):
            nonlocal respondido
            if excedido:
                if not respondido:
                    respondido = True
                    await self._rechazar(send)
                return
            await send(mensaje)

        await self.app(scope, receive_limitado, send_limitado)

    async def _rechazar(self, send):
        cuerpo = json.dumps({"detail": "Cuerpo demasiado grande."}).encode()
        await send({
            "type": "http.response.start", "status": 413,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(cuerpo)).encode())],
        })
        await send({"type": "http.response.body", "body": cuerpo})
