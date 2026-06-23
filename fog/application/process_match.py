"""ProcessIncomingMatch — caso de uso: a partir de la TrackedSequence ya
calculada (pose+tracking corrido frame a frame por track_consumer.py
mientras llegaba el video, ver PoseTrackingSession), extrae features y
publica hacia Cloud. Orquesta los puertos sin saber nada de ultralytics,
redis ni aiortc (eso vive en infrastructure/).

Antes este caso de uso recibía la lista cruda de frames y llamaba a
PoseEstimatorPort.detect_and_track sobre el clip completo (100% serial:
primero todo el tiempo real del clip, recién después todo el tiempo de
CPU de pose+features). Ahora pose+tracking ya corrió incrementalmente
mientras el clip se recibía (ver track_consumer.py), así que este caso de
uso ya no depende de PoseEstimatorPort en absoluto — solo de
FeatureExtractorPort, que ya operaba sobre TrackedSequence.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Executor

from fog.domain.models import LuzSignal, Match, TrackedSequence, WeaponSide
from fog.ports.feature_extractor import FeatureExtractorPort
from fog.ports.feature_publisher import FeatureStreamPublisherPort
from fog.ports.match_repository import MatchRepositoryPort

log = logging.getLogger("fog.application")


class ProcessIncomingMatch:
    def __init__(
        self,
        feature_extractor: FeatureExtractorPort,
        publisher: FeatureStreamPublisherPort,
        repository: MatchRepositoryPort,
        executor: Executor,
        min_frames: int = 3,
    ):
        self._feature_extractor = feature_extractor
        self._publisher = publisher
        self._repository = repository
        self._executor = executor
        self._min_frames = min_frames

    async def execute(
        self,
        match_id: str,
        tracked: TrackedSequence,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
        luz: LuzSignal | None,
    ) -> None:
        loop = asyncio.get_running_loop()

        features = await loop.run_in_executor(
            self._executor,
            self._feature_extractor.extract,
            tracked, weapon_side_a, weapon_side_b, self._min_frames,
        )

        if features.sequence is None:
            log.error("[%s] extracción falló: %s", match_id, features.stats.get("error"))
            return

        log.info("[%s] features extraídas: %s", match_id, features.stats.get("seq_shape"))

        effective_luz = luz if luz is not None else LuzSignal.none()
        await self._publisher.publish(match_id, features, effective_luz, weapon_side_a, weapon_side_b)
        await self._repository.save(Match(
            match_id=match_id,
            weapon_side_a=weapon_side_a,
            weapon_side_b=weapon_side_b,
            luz=effective_luz,
        ))
