"""Sonda de Redis para GET /health: `PING` con tiempo límite (el cliente
de Fog se crea con socket_timeout=None, así que sin este límite un Redis
caído dejaría colgado el endpoint)."""

import asyncio

from fog.ports.sonda_salud import SondaSaludPort


class RedisSonda(SondaSaludPort):
    def __init__(self, client, timeout_s: float = 2.0):
        self._client = client
        self._timeout_s = timeout_s

    async def responde(self) -> bool:
        try:
            await asyncio.wait_for(self._client.ping(), self._timeout_s)
        except Exception:
            return False
        return True
