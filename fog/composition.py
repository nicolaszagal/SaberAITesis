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

from fog.application.abrir_revision import AbrirRevisionVar
from fog.application.configurar_combate import ConfigurarCombate
from fog.application.forward_verdict import ForwardVerdictToClient
from fog.application.consultar_revisiones import (
    ConsultarSalud,
    ListarRevisiones,
    ObtenerModeloActivo,
    ObtenerRevision,
    VerificarAuditoria,
)
from fog.application.consultar_combate import ObtenerCombate
from fog.application.listar_catalogos import ListarEventos, ListarUsuarios
from fog.application.process_match import ProcessIncomingMatch
from fog.application.resumir_validacion import ResumirValidacion
from fog.application.registrar_clasificacion import RegistrarClasificacion
from fog.application.registrar_veredicto import RegistrarVeredicto
from fog.infrastructure.evidencia.fuente_modelo_m01 import FuenteModeloM01
from fog.infrastructure.evidencia.lector_jsonl import LectorEvidenciaJsonl
from fog.infrastructure.evidencia.registro_jsonl import RegistroEvidenciaJsonl
from fog.infrastructure.features.new192_feature_extractor import New192FeatureExtractor
from fog.infrastructure.features.preprocessing_profile import load_profile
from fog.infrastructure.messaging.redis_feature_publisher import RedisFeaturePublisher
from fog.infrastructure.messaging.redis_sonda_salud import RedisSonda
from fog.infrastructure.messaging.redis_verdict_subscriber import RedisVerdictSubscriber
from fog.infrastructure.persistence.database import build_engine, build_session_factory
from fog.infrastructure.persistence.in_memory_match_repository import (
    InMemoryMatchRepository,
)
from fog.infrastructure.persistence.postgres.auditoria_repository import (
    PostgresAuditoriaRepository,
)
from fog.infrastructure.persistence.postgres.clasificacion_repository import (
    PostgresClasificacionRepository,
)
from fog.infrastructure.persistence.postgres.clip_repository import (
    PostgresClipRepository,
)
from fog.infrastructure.persistence.postgres.combate_repository import (
    PostgresCombateRepository,
)
from fog.infrastructure.persistence.postgres.consulta_evidencia_repository import (
    PostgresConsultaEvidenciaRepository,
)
from fog.infrastructure.persistence.postgres.consulta_revision_repository import (
    PostgresConsultaRevisionRepository,
)
from fog.infrastructure.persistence.postgres.evento_repository import (
    PostgresEventoRepository,
)
from fog.infrastructure.persistence.postgres.modelo_version_repository import (
    PostgresModeloVersionRepository,
)
from fog.infrastructure.persistence.postgres.revision_repository import (
    PostgresRevisionRepository,
)
from fog.infrastructure.persistence.postgres.tocado_repository import (
    PostgresTocadoRepository,
)
from fog.infrastructure.persistence.postgres.sonda_salud import PostgresSonda
from fog.infrastructure.persistence.postgres.unidad_de_trabajo import (
    PostgresUnidadDeTrabajo,
)
from fog.infrastructure.persistence.postgres.verificador_auditoria import (
    PostgresVerificadorAuditoria,
)
from fog.infrastructure.persistence.postgres.veredicto_repository import (
    PostgresVeredictoRepository,
)
from fog.infrastructure.pose.yolo_pose_adapter import YoloV8PoseAdapter
from fog.infrastructure.storage.local_file_storage import LocalFileStorage
from fog.infrastructure.webrtc.session_registry import SessionRegistry


def _load_yolo_model(model_path: str) -> YOLO:
    return YOLO(model_path)


def _build_feature_extractor(
    stats_path: str, profile_name: str, profiles_path: str | None
) -> New192FeatureExtractor:
    stats = np.load(stats_path)
    profile = load_profile(profile_name, profiles_path)
    return New192FeatureExtractor(mean=stats["mean"], std=stats["std"], profile=profile)


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

    yolo_model = providers.Singleton(
        _load_yolo_model, model_path=config.yolo_pose_model_path
    )

    pose_estimator = providers.Singleton(YoloV8PoseAdapter, model=yolo_model)

    feature_extractor = providers.Singleton(
        _build_feature_extractor,
        stats_path=config.feature_stats_path,
        profile_name=config.feature_preprocessing_profile,
        profiles_path=config.feature_preprocessing_profiles_path,
    )

    # Match (agregado runtime de una sesión WebRTC/clip: weapon_side_a/b, luz,
    # verdict) no tiene tabla propia y no lleva evento_id/tirador/arbitro_id
    # de `sabre.combate` — D02 lo deja como está a propósito. D03 decide, al
    # implementar CU-01, cómo se relaciona con CombateRepositoryPort (abajo).
    match_repository = providers.Singleton(InMemoryMatchRepository)

    db_engine = providers.Singleton(build_engine, database_url=config.database_url)

    db_session_factory = providers.Singleton(build_session_factory, engine=db_engine)

    # Adaptadores del esquema de auditoría (D02, docs_claude/sabre_ai_schema.sql).
    # Los casos de uso de D03 no los usan sueltos: piden una transacción a
    # `unidad_de_trabajo`, que arma los mismos adaptadores sobre una sola
    # sesión (atomicidad de RF-21/RF-22).
    evento_repository = providers.Singleton(
        PostgresEventoRepository, session_factory=db_session_factory
    )
    combate_repository = providers.Singleton(
        PostgresCombateRepository, session_factory=db_session_factory
    )
    clip_repository = providers.Singleton(
        PostgresClipRepository, session_factory=db_session_factory
    )
    tocado_repository = providers.Singleton(
        PostgresTocadoRepository, session_factory=db_session_factory
    )
    modelo_version_repository = providers.Singleton(
        PostgresModeloVersionRepository, session_factory=db_session_factory
    )
    clasificacion_repository = providers.Singleton(
        PostgresClasificacionRepository, session_factory=db_session_factory
    )
    revision_repository = providers.Singleton(
        PostgresRevisionRepository, session_factory=db_session_factory
    )
    veredicto_repository = providers.Singleton(
        PostgresVeredictoRepository, session_factory=db_session_factory
    )
    auditoria_repository = providers.Singleton(
        PostgresAuditoriaRepository, session_factory=db_session_factory
    )

    file_storage = providers.Singleton(LocalFileStorage, root=config.storage_dir)

    unidad_de_trabajo = providers.Singleton(
        PostgresUnidadDeTrabajo, session_factory=db_session_factory
    )

    configurar_combate = providers.Singleton(ConfigurarCombate, uow=unidad_de_trabajo)

    abrir_revision = providers.Singleton(AbrirRevisionVar, uow=unidad_de_trabajo)

    registrar_clasificacion = providers.Singleton(
        RegistrarClasificacion, uow=unidad_de_trabajo, storage=file_storage
    )

    registro_evidencia = providers.Singleton(
        RegistroEvidenciaJsonl, directorio=config.evidence_dir
    )

    registrar_veredicto = providers.Singleton(
        RegistrarVeredicto, uow=unidad_de_trabajo, evidencia=registro_evidencia
    )

    listar_eventos = providers.Singleton(ListarEventos, uow=unidad_de_trabajo)

    obtener_combate = providers.Singleton(ObtenerCombate, uow=unidad_de_trabajo)

    listar_usuarios = providers.Singleton(ListarUsuarios, uow=unidad_de_trabajo)

    # Consultas de solo lectura para la interfaz (GET /revisiones, /auditoria,
    # /modelo/activo, /health).
    consulta_revision_repository = providers.Singleton(
        PostgresConsultaRevisionRepository, session_factory=db_session_factory
    )
    verificador_auditoria = providers.Singleton(
        PostgresVerificadorAuditoria, session_factory=db_session_factory
    )
    sonda_postgres = providers.Singleton(PostgresSonda, session_factory=db_session_factory)
    sonda_redis = providers.Singleton(RedisSonda, client=redis_client)

    listar_revisiones = providers.Singleton(
        ListarRevisiones, consulta=consulta_revision_repository
    )
    obtener_revision = providers.Singleton(
        ObtenerRevision, consulta=consulta_revision_repository
    )
    verificar_auditoria = providers.Singleton(
        VerificarAuditoria, verificador=verificador_auditoria
    )
    obtener_modelo_activo = providers.Singleton(
        ObtenerModeloActivo, modelos=modelo_version_repository
    )
    consultar_salud = providers.Singleton(
        ConsultarSalud, redis=sonda_redis, postgres=sonda_postgres
    )

    # Resumen de validación (L02): todo desde la base; el JSONL de L01 solo
    # se concilia. La tabla M01 sale del log de experimentos (solo lectura).
    consulta_evidencia_repository = providers.Singleton(
        PostgresConsultaEvidenciaRepository, session_factory=db_session_factory
    )
    lector_evidencia = providers.Singleton(
        LectorEvidenciaJsonl, directorio=config.evidence_dir
    )
    fuente_evidencia_modelo = providers.Singleton(
        FuenteModeloM01, ruta_log=config.m01_experiment_log
    )
    resumir_validacion = providers.Singleton(
        ResumirValidacion,
        consulta=consulta_evidencia_repository,
        lector=lector_evidencia,
        verificador=verificador_auditoria,
        modelos=modelo_version_repository,
        fuente_modelo=fuente_evidencia_modelo,
    )

    feature_publisher = providers.Singleton(RedisFeaturePublisher, client=redis_client)

    verdict_subscriber = providers.Singleton(
        RedisVerdictSubscriber, client=redis_client
    )

    sessions = providers.Singleton(SessionRegistry)

    process_match = providers.Singleton(
        ProcessIncomingMatch,
        feature_extractor=feature_extractor,
        publisher=feature_publisher,
        repository=match_repository,
        sessions=sessions,
        executor=executor,
        min_frames=config.min_frames,
    )

    forward_verdict = providers.Singleton(
        ForwardVerdictToClient,
        subscriber=verdict_subscriber,
        sessions=sessions,
    )
