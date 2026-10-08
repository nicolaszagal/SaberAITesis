"""RedisFeatureConsumer — implementación de FeatureStreamConsumerPort,
leyendo el stream `fog:features` vía el grupo de consumidores
`cloud_workers` (ver CONTRATO_API.md sección 3). Mirror de
`ensure_group`+el loop `xreadgroup` del cloud/main.py anterior.

Valida cada entrada contra el contrato (CONTRATO_API.md sección 5) antes de
convertirla en `FeatureSequence`: una entrada que no respeta el contrato
(campo faltante, shape/dtype/tamaño de buffer inconsistentes) ya no lanza
`ValueError` hacia el loop del caso de uso (DEF-09: eso mataba el proceso y
dejaba la entrada pendiente sin ACK, sin reintento posible al reiniciar
porque `XREADGROUP ">"` no relee pendientes). En su lugar se mueve a
`fog:features:dead` con el motivo y se hace ACK, y se yieldea un
`InvalidFeatureMessage` para que el caso de uso publique el veredicto "no
disponible" correspondiente.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import numpy as np
import redis.asyncio as redis
from redis.exceptions import ResponseError

from cloud.domain.models import (
    FeatureSequence, InvalidFeatureMessage, LuzSignal, MotivoNoDisponible,
)
from cloud.ports.feature_consumer import FeatureStreamConsumerPort
from shared import config

log = logging.getLogger("cloud.infrastructure")

# "T,192" — T = frames reales del clip, 192 = features por frame (A+B).
# Ver CONTRATO_API.md sección 5.
_EXPECTED_FEATURE_DIM = 192
_EXPECTED_DTYPE = "float32"
_REQUIRED_FIELDS = (
    b"match_id", b"revision_id", b"shape", b"dtype", b"features",
    b"weapon_side_A", b"weapon_side_B",
)


class InvalidMessageError(ValueError):
    """Una entrada de `fog:features` no respeta el contrato."""


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
            log.info(
                "Grupo de consumidores '%s' creado en '%s'",
                config.GROUP_CLOUD, config.STREAM_FEATURES,
            )
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            log.info("Grupo de consumidores '%s' ya existía", config.GROUP_CLOUD)
        self._group_ensured = True

    async def _reclaim_pending(self) -> list[tuple[str, dict]]:
        """XAUTOCLAIM de entradas pendientes con idle >= CLAIM_MIN_IDLE_S,
        para las que un worker anterior murió entre XREADGROUP y XACK
        (DEF-09) y que `XREADGROUP ">"` nunca vuelve a entregar."""
        min_idle_ms = int(config.CLAIM_MIN_IDLE_S * 1000)
        claimed: list[tuple[str, dict]] = []
        start_id = "0-0"
        while True:
            next_start_id, entries, *_rest = await self._client.xautoclaim(
                config.STREAM_FEATURES, config.GROUP_CLOUD, config.CONSUMER_CLOUD,
                min_idle_time=min_idle_ms, start_id=start_id, count=100,
            )
            claimed.extend(
                (eid.decode() if isinstance(eid, bytes) else eid, f)
                for eid, f in entries
            )
            if not entries or next_start_id in (b"0-0", "0-0"):
                break
            start_id = next_start_id
        if claimed:
            log.info("Reclamadas %d entradas pendientes de '%s' (min-idle=%ss)",
                      len(claimed), config.STREAM_FEATURES, config.CLAIM_MIN_IDLE_S)
        return claimed

    def _parse(self, fields: dict[bytes, bytes]) -> FeatureSequence:
        missing = [f.decode() for f in _REQUIRED_FIELDS if f not in fields]
        if missing:
            raise InvalidMessageError(f"campos faltantes: {', '.join(missing)}")

        dtype_str = fields[b"dtype"].decode(errors="replace")
        if dtype_str != _EXPECTED_DTYPE:
            raise InvalidMessageError(
                f"dtype inesperado: '{dtype_str}' (se espera '{_EXPECTED_DTYPE}')"
            )

        try:
            shape_str = fields[b"shape"].decode(errors="replace")
            shape = tuple(int(v) for v in shape_str.split(","))
        except ValueError:
            raise InvalidMessageError(f"shape inválido: {fields[b'shape']!r}") from None
        if len(shape) != 2 or shape[0] < 1 or shape[1] != _EXPECTED_FEATURE_DIM:
            raise InvalidMessageError(
                f"shape inesperado: {shape} (se espera (T>=1, {_EXPECTED_FEATURE_DIM}))"
            )

        buffer = fields[b"features"]
        expected_size = shape[0] * shape[1] * np.dtype(dtype_str).itemsize
        if len(buffer) != expected_size:
            raise InvalidMessageError(
                f"tamaño de buffer ({len(buffer)} bytes) no coincide con shape {shape} "
                f"y dtype '{dtype_str}' (esperado {expected_size} bytes)"
            )

        sequence = np.frombuffer(buffer, dtype=dtype_str).reshape(shape)
        luz = LuzSignal(
            has_luz_a=fields.get(b"has_luz_A", b"0") == b"1",
            has_luz_b=fields.get(b"has_luz_B", b"0") == b"1",
        )
        return FeatureSequence(
            match_id=fields[b"match_id"].decode(errors="replace"),
            revision_id=fields[b"revision_id"].decode(errors="replace"),
            sequence=sequence,
            luz=luz,
            weapon_side_a=fields[b"weapon_side_A"].decode(errors="replace"),
            weapon_side_b=fields[b"weapon_side_B"].decode(errors="replace"),
        )

    async def _dead_letter(
        self, entry_id: str, fields: dict[bytes, bytes], motivo: str
    ) -> None:
        dead_fields = {
            **fields,
            b"motivo": motivo.encode(),
            b"entry_id_original": entry_id.encode(),
        }
        await self._client.xadd(
            config.STREAM_FEATURES_DEAD, dead_fields,
            maxlen=config.STREAM_MAXLEN, approximate=True,
        )
        await self._client.xack(config.STREAM_FEATURES, config.GROUP_CLOUD, entry_id)

    async def _handle_entry(
        self, entry_id: str, fields: dict[bytes, bytes]
    ) -> tuple[str, FeatureSequence | InvalidFeatureMessage]:
        try:
            return entry_id, self._parse(fields)
        except InvalidMessageError as e:
            match_id_raw = fields.get(b"match_id")
            match_id = match_id_raw.decode(errors="replace") if match_id_raw else None
            revision_raw = fields.get(b"revision_id")
            revision_id = revision_raw.decode(errors="replace") if revision_raw else None
            log.error(
                "[%s/%s] mensaje inválido en '%s' (%s): %s",
                match_id or "?", revision_id or "?", config.STREAM_FEATURES, entry_id, e,
            )
            motivo = MotivoNoDisponible.MENSAJE_INVALIDO
            await self._dead_letter(entry_id, fields, motivo.value)
            return entry_id, InvalidFeatureMessage(
                match_id=match_id, revision_id=revision_id, motivo=motivo, detalle=str(e),
            )

    async def consume(
        self,
    ) -> AsyncIterator[tuple[str, FeatureSequence | InvalidFeatureMessage]]:
        await self._ensure_group()

        for entry_id, fields in await self._reclaim_pending():
            yield await self._handle_entry(entry_id, fields)

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
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                yield await self._handle_entry(entry_id, fields)

    async def ack(self, entry_id: str) -> None:
        await self._client.xack(config.STREAM_FEATURES, config.GROUP_CLOUD, entry_id)
