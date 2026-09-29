"""Tests de RedisFeatureConsumer contra fakeredis: validación de contrato,
dead-letter + ACK de mensajes malformados (DEF-09) y XAUTOCLAIM de
pendientes al arrancar.
"""

from __future__ import annotations

import numpy as np
import pytest
from fakeredis import aioredis as fakeredis

from cloud.domain.models import FeatureSequence, InvalidFeatureMessage
from cloud.infrastructure.messaging.redis_feature_consumer import RedisFeatureConsumer
from shared import config


@pytest.fixture
async def client():
    r = fakeredis.FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


def _valid_fields(match_id: str = "m1", t: int = 5, revision_id: str | None = None) -> dict:
    seq = np.zeros((t, 192), dtype=np.float32)
    return {
        "match_id": match_id,
        "revision_id": revision_id or f"r-{match_id}",
        "shape": f"{seq.shape[0]},{seq.shape[1]}",
        "dtype": str(seq.dtype),
        "features": seq.tobytes(),
        "weapon_side_A": "right",
        "weapon_side_B": "right",
        "has_luz_A": "0",
        "has_luz_B": "0",
    }


async def test_consume_yields_valid_feature_sequence(client):
    await client.xadd(config.STREAM_FEATURES, _valid_fields(match_id="m1"))
    consumer = RedisFeatureConsumer(client)

    aiter_ = consumer.consume()
    entry_id, item = await aiter_.__anext__()

    assert isinstance(item, FeatureSequence)
    assert item.match_id == "m1"
    assert item.revision_id == "r-m1"
    assert item.sequence.shape == (5, 192)
    assert item.sequence.dtype == np.float32

    await consumer.ack(entry_id)
    pending = await client.xpending(config.STREAM_FEATURES, config.GROUP_CLOUD)
    assert pending["pending"] == 0


async def test_consume_malformed_buffer_size_dead_letters_and_acks(client):
    fields = _valid_fields(match_id="m2")
    fields["features"] = fields["features"][:-4]  # buffer no coincide con shape/dtype
    await client.xadd(config.STREAM_FEATURES, fields)
    consumer = RedisFeatureConsumer(client)

    entry_id, item = await consumer.consume().__anext__()

    assert isinstance(item, InvalidFeatureMessage)
    assert item.match_id == "m2"
    assert item.revision_id == "r-m2"
    assert item.motivo.value == "mensaje_invalido"

    # ACKeado por el propio consumer al mover a dead-letter — no queda pendiente.
    pending = await client.xpending(config.STREAM_FEATURES, config.GROUP_CLOUD)
    assert pending["pending"] == 0

    dead = await client.xrange(config.STREAM_FEATURES_DEAD, "-", "+")
    assert len(dead) == 1
    _, dead_fields = dead[0]
    assert dead_fields[b"motivo"] == b"mensaje_invalido"
    assert dead_fields[b"match_id"] == b"m2"
    assert dead_fields[b"entry_id_original"].decode() == entry_id


async def test_consume_missing_required_field_dead_letters(client):
    fields = _valid_fields(match_id="m3")
    del fields["dtype"]
    await client.xadd(config.STREAM_FEATURES, fields)
    consumer = RedisFeatureConsumer(client)

    entry_id, item = await consumer.consume().__anext__()

    assert isinstance(item, InvalidFeatureMessage)
    assert item.match_id == "m3"
    dead = await client.xrange(config.STREAM_FEATURES_DEAD, "-", "+")
    assert len(dead) == 1


async def test_consume_wrong_dtype_dead_letters(client):
    fields = _valid_fields(match_id="m4")
    fields["dtype"] = "float64"
    await client.xadd(config.STREAM_FEATURES, fields)
    consumer = RedisFeatureConsumer(client)

    _, item = await consumer.consume().__anext__()

    assert isinstance(item, InvalidFeatureMessage)


async def test_consume_processes_valid_entry_after_malformed_one(client):
    bad_fields = _valid_fields(match_id="bad")
    bad_fields["features"] = bad_fields["features"][:-4]
    await client.xadd(config.STREAM_FEATURES, bad_fields)
    await client.xadd(config.STREAM_FEATURES, _valid_fields(match_id="good"))

    consumer = RedisFeatureConsumer(client)
    aiter_ = consumer.consume()

    _, first = await aiter_.__anext__()
    assert isinstance(first, InvalidFeatureMessage)

    entry_id, second = await aiter_.__anext__()
    assert isinstance(second, FeatureSequence)
    assert second.match_id == "good"
    await consumer.ack(entry_id)


async def test_reclaims_pending_entry_on_startup(client, monkeypatch):
    monkeypatch.setattr(config, "CLAIM_MIN_IDLE_S", 0.0)

    await client.xgroup_create(
        config.STREAM_FEATURES, config.GROUP_CLOUD, id="0", mkstream=True,
    )
    await client.xadd(config.STREAM_FEATURES, _valid_fields(match_id="stale"))
    # Un worker anterior leyó la entrada y murió antes de hacer ACK.
    read = await client.xreadgroup(
        groupname=config.GROUP_CLOUD, consumername="ghost-worker",
        streams={config.STREAM_FEATURES: ">"}, count=1,
    )
    stale_entry_id = read[0][1][0][0].decode()

    consumer = RedisFeatureConsumer(client)
    entry_id, item = await consumer.consume().__anext__()

    assert entry_id == stale_entry_id
    assert isinstance(item, FeatureSequence)
    assert item.match_id == "stale"

    await consumer.ack(entry_id)
    pending = await client.xpending(config.STREAM_FEATURES, config.GROUP_CLOUD)
    assert pending["pending"] == 0


async def test_does_not_reclaim_recently_pending_entry(client, monkeypatch):
    monkeypatch.setattr(config, "CLAIM_MIN_IDLE_S", 60.0)

    await client.xgroup_create(
        config.STREAM_FEATURES, config.GROUP_CLOUD, id="0", mkstream=True,
    )
    await client.xadd(config.STREAM_FEATURES, _valid_fields(match_id="fresh"))
    await client.xreadgroup(
        groupname=config.GROUP_CLOUD, consumername="ghost-worker",
        streams={config.STREAM_FEATURES: ">"}, count=1,
    )

    consumer = RedisFeatureConsumer(client)
    claimed = await consumer._reclaim_pending()

    assert claimed == []


async def test_consume_missing_revision_id_dead_letters_without_revision(client):
    """`revision_id` es obligatorio: sin él Cloud no sabe en qué stream
    responder, así que el mensaje es inválido y se conserva el match_id."""
    fields = _valid_fields(match_id="m9")
    del fields["revision_id"]
    await client.xadd(config.STREAM_FEATURES, fields)
    consumer = RedisFeatureConsumer(client)

    _, item = await consumer.consume().__anext__()

    assert isinstance(item, InvalidFeatureMessage)
    assert item.match_id == "m9"
    assert item.revision_id is None
    assert item.motivo.value == "mensaje_invalido"


async def test_consume_keeps_revision_id_of_each_entry_for_the_same_match(client):
    await client.xadd(config.STREAM_FEATURES, _valid_fields(match_id="m", revision_id="rev-1"))
    await client.xadd(config.STREAM_FEATURES, _valid_fields(match_id="m", revision_id="rev-2"))
    consumer = RedisFeatureConsumer(client)
    aiter_ = consumer.consume()

    _, primero = await aiter_.__anext__()
    _, segundo = await aiter_.__anext__()

    assert (primero.match_id, primero.revision_id) == ("m", "rev-1")
    assert (segundo.match_id, segundo.revision_id) == ("m", "rev-2")
