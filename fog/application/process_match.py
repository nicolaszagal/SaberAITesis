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

Si la extracción falla (DEF-08), este caso de uso entrega un
UnavailableResult directo a la sesión (SessionRegistry) en vez de
publicar en Redis — Cloud nunca se entera del match y no hay veredicto
que esperar. Sigue el mismo patrón que ForwardVerdictToClient (también en
application/, también depende de SessionRegistry para poder empujar el
mensaje por WebSocket apenas está disponible).
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Executor

from fog.domain.models import (
    LuzSignal,
    Match,
    MotivoNoDisponible,
    TrackedSequence,
    UnavailableResult,
    WeaponSide,
)
from fog.infrastructure.webrtc.session_registry import SessionRegistry
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
        tracked: TrackedSequence,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
        luz: LuzSignal | None,
    ) -> UnavailableResult | None:
        loop = asyncio.get_running_loop()

        features = await loop.run_in_executor(
            self._executor,
            self._feature_extractor.extract,
            tracked, weapon_side_a, weapon_side_b, self._min_frames,
        )

        if features.sequence is None:
            log.warning("[%s] extracción no disponible: %s", match_id, features.stats.get("error"))
            # Los dos únicos errores que devuelve FeatureExtractorPort hoy
            # ("tracking no pudo asignar IDs A/B" y "secuencia muy corta")
            # mapean a pose_incompleta (único motivo que Fog puede
            # determinar; ver MotivoNoDisponible).
            result = UnavailableResult(match_id=match_id, motivo=MotivoNoDisponible.POSE_INCOMPLETA)
            session = self._sessions.get(match_id)
            if session is not None:
                await session.set_unavailable(result)
                if session.ws is not None:
                    await session.ws.send_json(result.to_ws_message())
            return result

        log.info("[%s] features extraídas: %s", match_id, features.stats.get("seq_shape"))

        effective_luz = luz if luz is not None else LuzSignal.none()
        await self._publisher.publish(match_id, features, effective_luz, weapon_side_a, weapon_side_b)
        await self._repository.save(Match(
            match_id=match_id,
            weapon_side_a=weapon_side_a,
            weapon_side_b=weapon_side_b,
            luz=effective_luz,
        ))
        return None
