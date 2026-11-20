"""ClasificarSecuencia — caso de uso: clasifica una secuencia de features y devuelve el veredicto.

No sabe de transportes: lo usan `ClassifyAndPublish` (consumidor de Redis, que publica el
resultado) y la API HTTP de entrada (que lo devuelve en la respuesta). Así la lógica de
clasificación —modelo, política de arbitraje, tirador atribuido— existe una sola vez.
"""

from __future__ import annotations

import logging
import time

from cloud.domain.models import FeatureSequence, Verdict
from cloud.ports.action_classifier import ActionClassifierPort
from cloud.ports.arbitration_policy import ArbitrationPolicyPort
from shared import config

log = logging.getLogger("cloud.application")


class ClasificarSecuencia:
    def __init__(
        self,
        classifier: ActionClassifierPort,
        arbitration: ArbitrationPolicyPort,
        modelo_version_name: str,
    ):
        self._classifier = classifier
        self._arbitration = arbitration
        self._modelo_version_name = modelo_version_name

    def precalentar(self) -> None:
        """Precalienta el clasificador (F-027). La salida se descarta.

        Raises:
            Exception: si el precalentamiento falla; Cloud no debe arrancar.
        """
        inicio = time.perf_counter()
        self._classifier.precalentar()
        log.info("modelo precalentado en %d ms", (time.perf_counter() - inicio) * 1000)

    def execute(self, features: FeatureSequence) -> Verdict:
        """Clasifica la secuencia.

        Args:
            features: secuencia ya validada contra el contrato.

        Returns:
            El veredicto disponible, con clase, confianza, tirador, probabilidades,
            atención, latencia de inferencia y versión del modelo.

        Raises:
            Exception: cualquier falla del clasificador o de la política se propaga.
        """
        inicio = time.perf_counter()
        crudo = self._classifier.classify(features.sequence, features.luz)
        latencia_inferencia_ms = int((time.perf_counter() - inicio) * 1000)
        resuelto = self._arbitration.resolve(crudo, features.luz)

        lado = resuelto.action_class.value[-1]  # "A" o "B"
        tirador = config.FENCER_COLOR[lado]
        log.info(
            "[%s] veredicto: %s (%s) conf=%.3f",
            features.revision_id, resuelto.action_class.value, tirador, resuelto.confidence,
        )
        return Verdict(
            match_id=features.match_id,
            revision_id=features.revision_id,
            disponible=True,
            action_class=resuelto.action_class,
            confidence=resuelto.confidence,
            fencer=tirador,
            probs=resuelto.probs,
            latencia_inferencia_ms=latencia_inferencia_ms,
            modelo=self._modelo_version_name,
            atencion=resuelto.atencion,
        )
