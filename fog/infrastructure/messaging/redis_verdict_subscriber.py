"""RedisVerdictSubscriber — implementa VerdictStreamSubscriberPort leyendo
el stream `cloud:verdicts:{revision_id}` (ver CONTRATO_API.md sección 4).
"""

import asyncio
import json

import redis.asyncio as redis

from fog.domain.models import MotivoNoDisponible, UnavailableResult, VerdictView
from fog.ports.verdict_subscriber import VerdictStreamSubscriberPort
from shared import config


class RedisVerdictSubscriber(VerdictStreamSubscriberPort):
    def __init__(self, client: "redis.Redis"):
        self._client = client

    async def wait_for_verdict(self, revision_id: str) -> VerdictView | UnavailableResult:
        stream_key = f"{config.VERDICT_STREAM_PREFIX}{revision_id}"
        last_id = "0"
        while True:
            result = await self._client.xread({stream_key: last_id}, count=1, block=5000)
            if not result:
                await asyncio.sleep(0)
                continue
            _, entries = result[0]
            _, fields = entries[0]
            match_id = fields[b"match_id"].decode() if b"match_id" in fields else ""
            if fields.get(b"disponible", b"true").decode() == "false":
                return UnavailableResult(
                    match_id=match_id,
                    revision_id=revision_id,
                    motivo=MotivoNoDisponible(fields[b"motivo_no_disp"].decode()),
                )
            return VerdictView(
                match_id=match_id,
                revision_id=revision_id,
                fencer=fields[b"fencer"].decode(),
                action=fields[b"action_class"].decode(),
                confidence=float(fields[b"confidence"]),
                probs=json.loads(fields[b"probs"]) if b"probs" in fields else None,
                latencia_inferencia_ms=(
                    int(float(fields[b"latencia_inferencia_ms"]))
                    if b"latencia_inferencia_ms" in fields
                    else None
                ),
                modelo=fields[b"modelo"].decode() if b"modelo" in fields else None,
            )
