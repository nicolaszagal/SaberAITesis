"""RedisVerdictSubscriber — implementa VerdictStreamSubscriberPort leyendo
el stream `cloud:verdicts:{match_id}` (ver CONTRATO_API.md sección 4).
"""

import asyncio

import redis.asyncio as redis

from fog.domain.models import VerdictView
from fog.ports.verdict_subscriber import VerdictStreamSubscriberPort
from shared import config


class RedisVerdictSubscriber(VerdictStreamSubscriberPort):
    def __init__(self, client: "redis.Redis"):
        self._client = client

    async def wait_for_verdict(self, match_id: str) -> VerdictView:
        stream_key = f"{config.VERDICT_STREAM_PREFIX}{match_id}"
        last_id = "0"
        while True:
            result = await self._client.xread({stream_key: last_id}, count=1, block=5000)
            if not result:
                await asyncio.sleep(0)
                continue
            _, entries = result[0]
            _, fields = entries[0]
            return VerdictView(
                match_id=match_id,
                fencer=fields[b"fencer"].decode(),
                action=fields[b"action_class"].decode(),
                confidence=float(fields[b"confidence"]),
            )
