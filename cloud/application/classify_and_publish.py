"""ClassifyAndPublish — caso de uso: consume features de Fog, clasifica
(ActionClassifierPort), aplica la política de arbitraje
(ArbitrationPolicyPort), resuelve el color del tirador y publica el
veredicto final (VerdictPublisherPort). Mirror del loop `run()` del
cloud/main.py anterior, ahora orquestando puertos.

DEF-09: `run_forever` captura cualquier excepción por mensaje — una falla
procesando una entrada (clasificador, arbitraje, o el publisher) nunca
detiene el loop; solo se pierde el veredicto de esa entrada, que queda
registrado en el log. Una entrada que el consumer no pudo parsear llega
como `InvalidFeatureMessage`: ya fue movida a dead-letter y ACKeada por el
adaptador (ver RedisFeatureConsumer), así que acá solo se publica el
veredicto "no disponible".
"""

from __future__ import annotations

import logging
import time

from cloud.domain.models import InvalidFeatureMessage, Verdict
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
        modelo_version_name: str,
    ):
        self._consumer = consumer
        self._classifier = classifier
        self._arbitration = arbitration
        self._publisher = publisher
        self._modelo_version_name = modelo_version_name

    async def run_forever(self) -> None:
        async for entry_id, item in self._consumer.consume():
            try:
                await self._handle(entry_id, item)
            except Exception:
                match_id = getattr(item, "match_id", None) or "?"
                log.exception(
                    "[%s] fallo procesando entrada '%s', se continúa con la siguiente",
                    match_id, entry_id,
                )

    async def _handle(self, entry_id: str, item) -> None:
        if isinstance(item, InvalidFeatureMessage):
            if item.match_id is not None:
                await self._publisher.publish(Verdict(
                    match_id=item.match_id,
                    disponible=False,
                    motivo_no_disp=item.motivo.value,
                ))
            return

        features = item
        start = time.perf_counter()
        raw = self._classifier.classify(features.sequence, features.luz)
        latencia_inferencia_ms = int((time.perf_counter() - start) * 1000)
        resolved = self._arbitration.resolve(raw, features.luz)

        side = resolved.action_class.value[-1]  # "A" o "B"
        fencer = config.FENCER_COLOR[side]

        log.info(
            "[%s] veredicto: %s (%s) conf=%.3f",
            features.match_id, resolved.action_class.value, fencer, resolved.confidence,
        )

        await self._publisher.publish(Verdict(
            match_id=features.match_id,
            disponible=True,
            action_class=resolved.action_class,
            confidence=resolved.confidence,
            fencer=fencer,
            probs=resolved.probs,
            latencia_inferencia_ms=latencia_inferencia_ms,
            modelo=self._modelo_version_name,
        ))
        await self._consumer.ack(entry_id)
