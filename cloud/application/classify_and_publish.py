"""ClassifyAndPublish — caso de uso: consume features de Fog, clasifica
(ActionClassifierPort), aplica la política de arbitraje
(ArbitrationPolicyPort), resuelve el color del tirador y publica el
veredicto final (VerdictPublisherPort). Mirror del loop `run()` del
cloud/main.py anterior, ahora orquestando puertos.
"""

from __future__ import annotations

import logging

from cloud.domain.models import Verdict
from cloud.ports.action_classifier import ActionClassifierPort
from cloud.ports.arbitration_policy import ArbitrationPolicyPort
from cloud.ports.feature_consumer import FeatureStreamConsumerPort
from cloud.ports.verdict_publisher import VerdictPublisherPort
from shared import config

log = logging.getLogger("cloud.application")


class ClassifyAndPublish:
    def __init__(
        self,
        consumer: FeatureStreamConsumerPort,
        classifier: ActionClassifierPort,
        arbitration: ArbitrationPolicyPort,
        publisher: VerdictPublisherPort,
    ):
        self._consumer = consumer
        self._classifier = classifier
        self._arbitration = arbitration
        self._publisher = publisher

    async def run_forever(self) -> None:
        async for entry_id, features in self._consumer.consume():
            raw = self._classifier.classify(features.sequence, features.luz)
            resolved = self._arbitration.resolve(raw, features.luz)

            side = resolved.action_class.value[-1]  # "A" o "B"
            fencer = config.FENCER_COLOR[side]

            log.info(
                "[%s] veredicto: %s (%s) conf=%.3f",
                features.match_id, resolved.action_class.value, fencer, resolved.confidence,
            )

            await self._publisher.publish(Verdict(
                match_id=features.match_id,
                action_class=resolved.action_class,
                confidence=resolved.confidence,
                fencer=fencer,
            ))
            await self._consumer.ack(entry_id)
