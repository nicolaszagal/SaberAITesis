"""RedisFeatureConsumer — implementación de FeatureStreamConsumerPort,
leyendo el stream `fog:features` vía el grupo de consumidores
`cloud_workers` (ver CONTRATO_API.md sección 3). Mirror de
`ensure_group`+el loop `xreadgroup` del cloud/main.py anterior.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import numpy as np
import redis.asyncio as redis
from redis.exceptions import ResponseError

from cloud.domain.models import FeatureSequence, LuzSignal
from cloud.ports.feature_consumer import FeatureStreamConsumerPort
from shared import config

log = logging.getLogger("cloud.infrastructure")


class RedisFeatureConsumer(FeatureStreamConsumerPort):
    def __init__(self, client: "redis.Redis"):
        self._client = client
        self._group_ensured = False

    async def _ensure_group(self) -> None:
        if self._group_ensured:
            return
        try:
            await self._client.xgroup_create(
                config.STREAM_FEATURES, config.GROUP_CLOUD, id="0", mkstream=True
            )
            log.info("Grupo de consumidores '%s' creado en '%s'", config.GROUP_CLOUD, config.STREAM_FEATURES)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            log.info("Grupo de consumidores '%s' ya existía", config.GROUP_CLOUD)
        self._group_ensured = True

    async def consume(self) -> AsyncIterator[tuple[str, FeatureSequence]]:
        await self._ensure_group()
        while True:
            result = await self._client.xreadgroup(
                groupname=config.GROUP_CLOUD,
                consumername=config.CONSUMER_CLOUD,
                streams={config.STREAM_FEATURES: ">"},
                count=1,
                block=5000,
            )
            if not result:
                continue

            _, entries = result[0]
            for entry_id, fields in entries:
                match_id = fields[b"match_id"].decode()
                shape = tuple(int(v) for v in fields[b"shape"].decode().split(","))
                dtype = fields[b"dtype"].decode()
                sequence = np.frombuffer(fields[b"features"], dtype=dtype).reshape(shape)

                luz = LuzSignal(
                    has_luz_a=fields.get(b"has_luz_A", b"0") == b"1",
                    has_luz_b=fields.get(b"has_luz_B", b"0") == b"1",
                )

                yield entry_id, FeatureSequence(
                    match_id=match_id,
                    sequence=sequence,
                    luz=luz,
                    weapon_side_a=fields[b"weapon_side_A"].decode(),
                    weapon_side_b=fields[b"weapon_side_B"].decode(),
                )

    async def ack(self, entry_id: str) -> None:
        await self._client.xack(config.STREAM_FEATURES, config.GROUP_CLOUD, entry_id)
