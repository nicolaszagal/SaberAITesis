"""Composition root de Fog — único lugar que conoce todas las
implementaciones concretas e instancia el grafo de dependencias. Usa
dependency_injector (decisión explícita de Nicolas, ver
PLAN_ARQUITECTURA_DDD.md sección 1) en vez de wiring manual.

main.py solo crea el Container, lo configura desde shared.config y lo
"wirea" contra infrastructure/api/routes.py.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import redis.asyncio as redis
from dependency_injector import containers, providers
from ultralytics import YOLO

from fog.application.forward_verdict import ForwardVerdictToClient
from fog.application.process_match import ProcessIncomingMatch
from fog.infrastructure.features.new192_feature_extractor import New192FeatureExtractor
from fog.infrastructure.messaging.redis_feature_publisher import RedisFeaturePublisher
from fog.infrastructure.messaging.redis_verdict_subscriber import RedisVerdictSubscriber
from fog.infrastructure.persistence.in_memory_match_repository import InMemoryMatchRepository
from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter
from fog.infrastructure.webrtc.session_registry import SessionRegistry


def _load_yolo_model(model_path: str) -> YOLO:
    return YOLO(model_path)


def _build_feature_extractor(stats_path: str, ablate_indices: list[int]) -> New192FeatureExtractor:
    stats = np.load(stats_path)
    return New192FeatureExtractor(
        mean=stats["mean"], std=stats["std"], ablate_indices=ablate_indices
    )


def _build_redis_client(redis_url: str) -> "redis.Redis":
    # socket_timeout=None: ver nota en cloud/composition.py. RedisVerdictSubscriber
    # hace xread(..., block=5000) en loop; con el timeout de socket de redis-py 8.x
    # (5s por default) corriendo en paralelo al BLOCK del servidor, el cliente
    # puede lanzar TimeoutError antes de que el BLOCK vacío vuelva.
    return redis.from_url(redis_url, decode_responses=False, socket_timeout=None)


class Container(containers.DeclarativeContainer):
    config = providers.Configuration()

    executor = providers.Singleton(ThreadPoolExecutor, max_workers=2)

    redis_client = providers.Singleton(_build_redis_client, redis_url=config.redis_url)

    yolo_model = providers.Singleton(_load_yolo_model, model_path=config.yolo_pose_model_path)

    pose_estimator = providers.Singleton(YoloV8PoseAdapter, model=yolo_model)

    feature_extractor = providers.Singleton(
        _build_feature_extractor,
        stats_path=config.feature_stats_path,
        ablate_indices=config.ablate_indices,
    )

    match_repository = providers.Singleton(InMemoryMatchRepository)

    feature_publisher = providers.Singleton(RedisFeaturePublisher, client=redis_client)

    verdict_subscriber = providers.Singleton(RedisVerdictSubscriber, client=redis_client)

    sessions = providers.Singleton(SessionRegistry)

    process_match = providers.Singleton(
        ProcessIncomingMatch,
        feature_extractor=feature_extractor,
        publisher=feature_publisher,
        repository=match_repository,
        executor=executor,
        min_frames=config.min_frames,
    )

    forward_verdict = providers.Singleton(
        ForwardVerdictToClient,
        subscriber=verdict_subscriber,
        sessions=sessions,
    )
