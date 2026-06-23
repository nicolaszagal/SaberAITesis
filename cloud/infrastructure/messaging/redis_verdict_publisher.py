"""RedisVerdictPublisher — implementación de VerdictPublisherPort,
publicando en `cloud:verdicts:{match_id}` (ver CONTRATO_API.md sección 4).
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as redis

from cloud.domain.models import Verdict
from cloud.ports.verdict_publisher import VerdictPublisherPort
from shared import config


class RedisVerdictPublisher(VerdictPublisherPort):
    def __init__(self, client: "redis.Redis"):
        self._client = client

    async def publish(self, verdict: Verdict) -> None:
        await self._client.xadd(
            f"{config.VERDICT_STREAM_PREFIX}{verdict.match_id}",
            {
                "match_id": verdict.match_id,
                "action_class": verdict.action_class.value,
                "confidence": f"{verdict.confidence:.6f}",
                "fencer": verdict.fencer,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )
