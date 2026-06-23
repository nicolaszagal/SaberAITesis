"""Fakes de los puertos de Cloud, para tests unitarios de application/."""

from __future__ import annotations

from typing import AsyncIterator

import numpy as np

from cloud.domain.models import FeatureSequence, LuzSignal, RawVerdict, Verdict
from cloud.ports.action_classifier import ActionClassifierPort
from cloud.ports.arbitration_policy import ArbitrationPolicyPort
from cloud.ports.feature_consumer import FeatureStreamConsumerPort
from cloud.ports.verdict_publisher import VerdictPublisherPort


class FakeFeatureConsumer(FeatureStreamConsumerPort):
    def __init__(self, items: list[tuple[str, FeatureSequence]]):
        self._items = items
        self.acked: list[str] = []

    async def consume(self) -> AsyncIterator[tuple[str, FeatureSequence]]:
        for entry_id, seq in self._items:
            yield entry_id, seq

    async def ack(self, entry_id: str) -> None:
        self.acked.append(entry_id)


class FakeActionClassifier(ActionClassifierPort):
    def __init__(self, result: RawVerdict):
        self.result = result
        self.calls: list[tuple] = []

    def classify(self, sequence: np.ndarray, luz: LuzSignal | None) -> RawVerdict:
        self.calls.append((sequence, luz))
        return self.result


class IdentityArbitrationPolicy(ArbitrationPolicyPort):
    """No-op: devuelve el veredicto crudo sin cambios (para aislar
    ClassifyAndPublish del comportamiento real de FaveroHardMaskPolicy)."""

    def resolve(self, raw: RawVerdict, luz: LuzSignal | None) -> RawVerdict:
        return raw


class FakeVerdictPublisher(VerdictPublisherPort):
    def __init__(self):
        self.published: list[Verdict] = []

    async def publish(self, verdict: Verdict) -> None:
        self.published.append(verdict)
