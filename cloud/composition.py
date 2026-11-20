"""Composition root de Cloud — análogo a fog/composition.py.

Cloud tiene dos adaptadores de entrada sobre el mismo caso de uso de clasificación: el
consumidor de Redis Streams (modo local) y la API HTTP (DEPLOY11, modo remoto). Los
proveedores de Redis solo se instancian si main.py los pide, así que sin `REDIS_URL` Cloud
corre solo con HTTP y no abre ninguna conexión a Redis.
"""

from __future__ import annotations

import redis.asyncio as redis
import torch
from dependency_injector import containers, providers

from cloud.application.classify_and_publish import ClassifyAndPublish
from cloud.application.clasificar_secuencia import ClasificarSecuencia
from cloud.infrastructure.api.app import crear_app
from cloud.infrastructure.api.nodos import RegistroNodos
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
    # FIX04: con socket_timeout=None un corte de la red dejaba a Cloud bloqueado para siempre.
    # El socket tiene tiempo de espera (mayor que el BLOCK del XREADGROUP; ver
    # shared.config.cloud_redis_kwargs) y RedisFeatureConsumer sale tras N fallos seguidos.
    return redis.from_url(
        redis_url,
        decode_responses=False,
        **shared_config.cloud_redis_kwargs(),
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

    clasificar_secuencia = providers.Singleton(
        ClasificarSecuencia,
        classifier=classifier,
        arbitration=arbitration_policy,
        modelo_version_name=model_version_name,
    )

    # Entrada HTTP (DEPLOY11): solo si hay hashes de nodos (CLOUD_NODOS_SHA256).
    registro_nodos = providers.Singleton(
        lambda texto: RegistroNodos.desde_texto(texto), texto=config.nodos_sha256
    )

    api_http = providers.Singleton(
        crear_app, clasificar=clasificar_secuencia, nodos=registro_nodos
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
