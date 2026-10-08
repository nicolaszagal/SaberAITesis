"""Composition root de Cloud — análogo a fog/composition.py. Cloud no
expone API HTTP (es un consumidor de Redis Streams puro), por lo que no
hay wiring de FastAPI aquí: main.py simplemente instancia el Container y
llama al caso de uso directamente.
"""

from __future__ import annotations

import redis.asyncio as redis
import torch
from dependency_injector import containers, providers

from cloud.application.classify_and_publish import ClassifyAndPublish
from cloud.infrastructure.arbitration.null_arbitration_policy import (
    NullArbitrationPolicy,
)
from cloud.infrastructure.classifier.lstm6class_adapter import LSTM6ClassAdapter
from cloud.infrastructure.messaging.redis_feature_consumer import RedisFeatureConsumer
from cloud.infrastructure.messaging.redis_verdict_publisher import RedisVerdictPublisher
from shared import config as shared_config


def _select_device() -> "torch.device":
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _build_redis_client(redis_url: str) -> "redis.Redis":
    # socket_timeout=None: redis-py 8.x pone un default de 5s en el socket de
    # lectura. RedisFeatureConsumer hace xreadgroup(..., block=5000) en loop
    # (espera bloqueante del lado del servidor) — con el timeout de socket
    # también en 5s, el cliente puede cortar la lectura antes de que Redis
    # devuelva el BLOCK vacío, lanzando TimeoutError. La espera ya está
    # acotada por el BLOCK de cada comando; el socket no necesita timeout propio.
    return redis.from_url(
        redis_url,
        decode_responses=False,
        socket_timeout=None,
        **shared_config.redis_tls_kwargs(),
    )


class Container(containers.DeclarativeContainer):
    config = providers.Configuration()

    device = providers.Singleton(_select_device)

    redis_client = providers.Singleton(_build_redis_client, redis_url=config.redis_url)

    classifier = providers.Singleton(
        LSTM6ClassAdapter,
        run_dir=config.model_run_dir,
        device=device,
    )

    arbitration_policy = providers.Singleton(NullArbitrationPolicy)

    model_version_name = providers.Singleton(
        LSTM6ClassAdapter.model_version_name, run_dir=config.model_run_dir,
    )

    feature_consumer = providers.Singleton(RedisFeatureConsumer, client=redis_client)

    verdict_publisher = providers.Singleton(RedisVerdictPublisher, client=redis_client)

    classify_and_publish = providers.Singleton(
        ClassifyAndPublish,
        consumer=feature_consumer,
        classifier=classifier,
        arbitration=arbitration_policy,
        publisher=verdict_publisher,
        modelo_version_name=model_version_name,
    )
