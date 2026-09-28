"""Tests de RedisVerdictPublisher contra fakeredis: contrato del stream
`cloud:verdicts:{match_id}` y su TTL (DEF-16 — antes el stream no expiraba
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


def _verdict(match_id: str = "m1") -> Verdict:
    return Verdict(
        match_id=match_id,
        disponible=True,
        action_class=ActionClass.ATTACK_A,
        confidence=0.9,
        fencer="ROJ",
        probs={"AttackA": 0.9, "AttackB": 0.05, "ResponseA": 0.03, "ResponseB": 0.02},
        latencia_inferencia_ms=10,
        modelo="test-model",
    )


async def test_publish_sets_expire_on_verdict_stream(client, monkeypatch):
    monkeypatch.setattr(config, "VERDICT_STREAM_TTL_S", 3600)
    publisher = RedisVerdictPublisher(client)

    await publisher.publish(_verdict("m1"))

    ttl = await client.ttl(f"{config.VERDICT_STREAM_PREFIX}m1")
    assert 0 < ttl <= 3600


async def test_publish_uses_configured_ttl(client, monkeypatch):
    monkeypatch.setattr(config, "VERDICT_STREAM_TTL_S", 7)
    publisher = RedisVerdictPublisher(client)

    await publisher.publish(_verdict("m2"))

    ttl = await client.ttl(f"{config.VERDICT_STREAM_PREFIX}m2")
    assert 0 < ttl <= 7


async def test_publish_sets_expire_on_unavailable_verdict_too(client, monkeypatch):
    monkeypatch.setattr(config, "VERDICT_STREAM_TTL_S", 3600)
    publisher = RedisVerdictPublisher(client)
    verdict = Verdict(match_id="m3", disponible=False, motivo_no_disp="pose_incompleta")

    await publisher.publish(verdict)

    ttl = await client.ttl(f"{config.VERDICT_STREAM_PREFIX}m3")
    assert 0 < ttl <= 3600
