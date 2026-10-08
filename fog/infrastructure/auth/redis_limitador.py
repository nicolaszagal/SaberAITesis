"""Limitador de intentos de login por IP sobre Redis, con TTL."""

import redis.asyncio as redis

from fog.ports.limitador_intentos import LimitadorIntentosPort


class RedisLimitador(LimitadorIntentosPort):
    def __init__(
        self, client: "redis.Redis", max_fallos: int, ventana_s: int, bloqueo_s: int
    ):
        self._r = client
        self._max = max_fallos
        self._ventana_s = ventana_s
        self._bloqueo_s = bloqueo_s

    @staticmethod
    def _k_fallos(ip: str) -> str:
        return f"auth:fallos:{ip}"

    @staticmethod
    def _k_bloqueo(ip: str) -> str:
        return f"auth:bloqueo:{ip}"

    async def segundos_bloqueado(self, ip: str) -> int:
        ttl = await self._r.ttl(self._k_bloqueo(ip))
        return max(int(ttl), 0)

    async def registrar_fallo(self, ip: str) -> bool:
        clave = self._k_fallos(ip)
        fallos = await self._r.incr(clave)
        if fallos == 1:
            await self._r.expire(clave, self._ventana_s)
        if fallos < self._max:
            return False
        await self._r.set(self._k_bloqueo(ip), "1", ex=self._bloqueo_s)
        await self._r.delete(clave)
        return True

    async def registrar_exito(self, ip: str) -> None:
        await self._r.delete(self._k_fallos(ip))
