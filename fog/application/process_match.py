"""ProcessIncomingMatch — caso de uso: a partir de la TrackedSequence ya
calculada (pose+tracking corrido frame a frame por track_consumer.py
mientras llegaba el video, ver PoseTrackingSession), extrae features y
publica hacia Cloud. Orquesta los puertos sin saber nada de ultralytics,
redis (eso vive en infrastructure/).

Antes este caso de uso recibía la lista cruda de frames y llamaba a
PoseEstimatorPort.detect_and_track sobre el clip completo (100% serial:
primero todo el tiempo real del clip, recién después todo el tiempo de
CPU de pose+features). Ahora pose+tracking ya corrió incrementalmente
mientras el clip se recibía (ver track_consumer.py), así que este caso de
uso ya no depende de PoseEstimatorPort en absoluto — solo de
FeatureExtractorPort, que ya operaba sobre TrackedSequence.

Si la extracción falla (DEF-08), este caso de uso entrega un
UnavailableResult directo a la sesión (SessionRegistry) en vez de
publicar en Redis — Cloud nunca se entera de la revisión y no hay
veredicto que esperar. Cada revisión (un clip) tiene su propia sesión,
identificada por `revision_id`. Sigue el mismo patrón que ForwardVerdictToClient (también en
application/, también depende de SessionRegistry).
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Executor

from fog.domain.models import (
    LuzSignal,
    Match,
    MotivoNoDisponible,
    TrackedSequence,
    UnavailableResult,
    WeaponSide,
)
from fog.infrastructure.sesiones.session_registry import SessionRegistry
from fog.ports.feature_extractor import FeatureExtractorPort
from fog.ports.feature_publisher import FeatureStreamPublisherPort
from fog.ports.match_repository import MatchRepositoryPort
from shared import tiempos

log = logging.getLogger("fog.application")


class ProcessIncomingMatch:
    def __init__(
        self,
        feature_extractor: FeatureExtractorPort,
        publisher: FeatureStreamPublisherPort,
        repository: MatchRepositoryPort,
        sessions: SessionRegistry,
        executor: Executor,
        min_frames: int = 3,
    ):
        self._feature_extractor = feature_extractor
        self._publisher = publisher
        self._repository = repository
        self._sessions = sessions
        self._executor = executor
        self._min_frames = min_frames

    async def execute(
        self,
        match_id: str,
        revision_id: str,
        tracked: TrackedSequence,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
        luz: LuzSignal | None,
    ) -> UnavailableResult | None:
        loop = asyncio.get_running_loop()

        t_envio = time.perf_counter()
        inicio_hilo: list[float] = []  # ESTRES01: cuándo un hilo del executor tomó el trabajo

        def _extraer():
            if tiempos.activo():
                inicio_hilo.append(time.perf_counter())
            return self._feature_extractor.extract(tracked, weapon_side_a, weapon_side_b, self._min_frames)

        features = await loop.run_in_executor(self._executor, _extraer)
        t_features = time.perf_counter()

        if features.sequence is None:
            log.warning("[%s] extracción no disponible: %s", revision_id, features.stats.get("error"))
            # Los dos únicos errores que devuelve FeatureExtractorPort hoy
            # ("tracking no pudo asignar IDs A/B" y "secuencia muy corta")
            # mapean a pose_incompleta (único motivo que Fog puede
            # determinar; ver MotivoNoDisponible).
            result = UnavailableResult(
                match_id=match_id, revision_id=revision_id, motivo=MotivoNoDisponible.POSE_INCOMPLETA
            )
            session = self._sessions.get(revision_id)
            if session is not None:
                await session.set_unavailable(result)
            return result

        log.info("[%s] features extraídas: %s", revision_id, features.stats.get("seq_shape"))

        effective_luz = luz if luz is not None else LuzSignal.none()
        await self._publisher.publish(
            match_id, revision_id, features, effective_luz, weapon_side_a, weapon_side_b
        )
        if tiempos.activo():
            tiempos.registrar(
                "features", revision=revision_id,
                espera_executor_s=(inicio_hilo[0] - t_envio) if inicio_hilo else 0.0,
                features_s=t_features - (inicio_hilo[0] if inicio_hilo else t_envio),
                publicar_s=time.perf_counter() - t_features,
            )
        await self._repository.save(Match(
            match_id=match_id,
            weapon_side_a=weapon_side_a,
            weapon_side_b=weapon_side_b,
            luz=effective_luz,
        ))
        return None
