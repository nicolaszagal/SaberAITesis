"""RedisVerdictPublisher — implementación de VerdictPublisherPort,
publicando en `cloud:verdicts:{match_id}` (ver CONTRATO_API.md sección 6).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import redis.asyncio as redis

from cloud.domain.models import Verdict
from cloud.ports.verdict_publisher import VerdictPublisherPort
from shared import config


class RedisVerdictPublisher(VerdictPublisherPort):
    def __init__(self, client: "redis.Redis"):
        self._client = client

    async def publish(self, verdict: Verdict) -> None:
        fields = {
            "match_id": verdict.match_id,
            "disponible": "true" if verdict.disponible else "false",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if verdict.disponible:
            fields.update({
                "action_class": verdict.action_class.value,
                "confidence": f"{verdict.confidence:.6f}",
                "fencer": verdict.fencer,
                "probs": json.dumps(verdict.probs),
                "latencia_inferencia_ms": str(verdict.latencia_inferencia_ms),
                "modelo": verdict.modelo or "",
            })
        else:
            fields["motivo_no_disp"] = verdict.motivo_no_disp

        stream_key = f"{config.VERDICT_STREAM_PREFIX}{verdict.match_id}"
        await self._client.xadd(stream_key, fields)
        # DEF-16: sin EXPIRE, un match_id sin consumidor (Fog caído, o
        # nadie llamó a GET /ws/veredicto/{match_id}) deja el stream en
        # Redis para siempre.
        await self._client.expire(stream_key, config.VERDICT_STREAM_TTL_S)
