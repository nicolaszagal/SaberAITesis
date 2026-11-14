"""La sonda de Redis de GET /health responde `False` también si el PING nunca contesta (FIX04):
el cliente de Fog no tiene tiempo de espera de socket y una tailnet cortada no debe colgar el endpoint."""

import asyncio
import time

from fog.infrastructure.messaging.redis_sonda_salud import RedisSonda


class _PingQueNoContesta:
    async def ping(self):
        await asyncio.sleep(3600)


class _PingQueResponde:
    async def ping(self):
        return True


async def test_ping_colgado_se_reporta_caido_dentro_del_limite():
    sonda = RedisSonda(_PingQueNoContesta(), timeout_s=0.2)

    t0 = time.monotonic()
    responde = await sonda.responde()

    assert responde is False
    assert time.monotonic() - t0 < 2


async def test_ping_normal_se_reporta_ok():
    assert await RedisSonda(_PingQueResponde(), timeout_s=0.2).responde() is True
