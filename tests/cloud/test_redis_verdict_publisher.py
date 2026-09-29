"""Tests de RedisVerdictPublisher contra fakeredis: contrato del stream
`cloud:verdicts:{revision_id}` y su TTL (DEF-16 — antes el stream no expiraba
nunca)."""

from __future__ import annotations

import pytest
from fakeredis import aioredis as fakeredis

from cloud.domain.models import ActionClass, Verdict
from cloud.infrastructure.messaging.redis_verdict_publisher import RedisVerdictPublisher
from shared import config


@pytest.fixture
async def client():
    r = fakeredis.FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


def _verdict(revision_id: str = "r1", match_id: str = "m") -> Verdict:
    return Verdict(
        match_id=match_id,
        revision_id=revision_id,
        disponible=True,
        action_class=ActionClass.ATTACK_A,
        confidence=0.9,
        fencer="ROJ",
        probs={"AttackA": 0.9, "AttackB": 0.05, "ContrattackA": 0.03, "ContrattackB": 0.01,
               "RiposteA": 0.005, "RiposteB": 0.005},
        latencia_inferencia_ms=10,
        modelo="test-model",
    )


async def test_publish_sets_expire_on_verdict_stream(client, monkeypatch):
    monkeypatch.setattr(config, "VERDICT_STREAM_TTL_S", 3600)
    publisher = RedisVerdictPublisher(client)

    await publisher.publish(_verdict("r1"))

    ttl = await client.ttl(f"{config.VERDICT_STREAM_PREFIX}r1")
    assert 0 < ttl <= 3600


async def test_publish_uses_configured_ttl(client, monkeypatch):
    monkeypatch.setattr(config, "VERDICT_STREAM_TTL_S", 7)
    publisher = RedisVerdictPublisher(client)

    await publisher.publish(_verdict("r2"))

    ttl = await client.ttl(f"{config.VERDICT_STREAM_PREFIX}r2")
    assert 0 < ttl <= 7


async def test_publish_sets_expire_on_unavailable_verdict_too(client, monkeypatch):
    monkeypatch.setattr(config, "VERDICT_STREAM_TTL_S", 3600)
    publisher = RedisVerdictPublisher(client)
    verdict = Verdict(match_id="m", revision_id="r3", disponible=False, motivo_no_disp="pose_incompleta")

    await publisher.publish(verdict)

    ttl = await client.ttl(f"{config.VERDICT_STREAM_PREFIX}r3")
    assert 0 < ttl <= 3600


async def test_publish_uses_one_stream_per_revision_of_the_same_match(client):
    publisher = RedisVerdictPublisher(client)

    await publisher.publish(_verdict("rev-1", match_id="mismo"))
    await publisher.publish(_verdict("rev-2", match_id="mismo"))

    for revision_id in ("rev-1", "rev-2"):
        entradas = await client.xrange(f"{config.VERDICT_STREAM_PREFIX}{revision_id}", "-", "+")
        assert len(entradas) == 1
        campos = entradas[0][1]
        assert campos[b"revision_id"] == revision_id.encode()
        assert campos[b"match_id"] == b"mismo"
    assert await client.exists(f"{config.VERDICT_STREAM_PREFIX}mismo") == 0


async def test_publish_omits_match_id_when_unknown(client):
    publisher = RedisVerdictPublisher(client)
    verdict = Verdict(match_id=None, revision_id="r7", disponible=False, motivo_no_disp="mensaje_invalido")

    await publisher.publish(verdict)

    campos = (await client.xrange(f"{config.VERDICT_STREAM_PREFIX}r7", "-", "+"))[0][1]
    assert b"match_id" not in campos
    assert campos[b"revision_id"] == b"r7"
