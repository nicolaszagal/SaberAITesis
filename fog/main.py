"""
Fog — API Gateway (FastAPI) + WebRTC (aiortc) + cliente Redis Streams.

Responsabilidades (ver ../CONTRATO_API.md):
  1. POST /matches/config — paso previo: crea el combate, genera match_id y
     fija weapon_side_A/B antes de que llegue el video.
  2. POST /webrtc/offer — recibe oferta SDP + config de combate del front
     (Edge), arma la pista de video, devuelve la respuesta SDP.
  3. POST /webrtc/{match_id}/luz — recibe la señal de luz Favero (RJ11,
     fuera de alcance de este backend) antes de que termine el clip.
  4. POST /matches/{match_id}/clip — alternativa a 2+3 para subir un clip
     ya grabado (sin WebRTC) junto con los frames de señal Favero;
     abre una revisión (un combate admite N) y responde con la sugerencia
     de forma síncrona, incluido su revision_id.
  5. Procesa los frames del clip (WebRTC o subido) frame a frame en
     cuanto llegan (PoseTrackingSession, ver ports/pose_estimator.py) y
     extrae features 192-dim al finalizar (FeatureExtractorPort).
  6. Publica las features en el stream Redis "fog:features" para Cloud.
  7. Escucha el stream de veredicto de Cloud ("cloud:verdicts:{revision_id}")
     y lo reenvía al front por WebSocket (/ws/veredicto/{revision_id}).
  8. POST /revisiones/{revision_id}/veredicto — registra la decisión del
     árbitro sobre esa revisión y la cierra.

Arquitectura DDD/hexagonal: domain/, ports/, application/, infrastructure/
(ver PLAN_ARQUITECTURA_DDD.md). Este archivo solo ensambla el Container
(composition.py) y expone la app FastAPI — no contiene lógica de negocio.

Ejecutar (desde backend/):
    uvicorn fog.main:app --host 0.0.0.0 --port 8001
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fog.composition import Container
from fog.infrastructure.api import routes
from shared import config
from shared.logging_config import configurar_logging_tecnico

configurar_logging_tecnico()
log = logging.getLogger("fog")

config.require_paths(
    "FEATURE_STATS_PATH", "FEATURE_PREPROCESSING_PROFILE", "EVIDENCE_DIR"
)

container = Container()
container.config.redis_url.from_value(config.REDIS_URL)
container.config.yolo_pose_model_path.from_value(config.YOLO_POSE_MODEL_PATH)
container.config.feature_stats_path.from_value(config.FEATURE_STATS_PATH)
container.config.feature_preprocessing_profile.from_value(config.FEATURE_PREPROCESSING_PROFILE)
container.config.feature_preprocessing_profiles_path.from_value(config.FEATURE_PREPROCESSING_PROFILES_PATH)
container.config.database_url.from_value(config.DATABASE_URL)
container.config.storage_dir.from_value(config.STORAGE_DIR)
container.config.evidence_dir.from_value(config.EVIDENCE_DIR)
container.config.m01_experiment_log.from_value(config.M01_EXPERIMENT_LOG)
container.config.min_frames.from_value(config.MIN_FRAMES)
container.config.clip_max_mb.from_value(config.CLIP_MAX_MB)
container.config.luz_timeout_s.from_value(config.FAVERO_LUZ_TIMEOUT_S)
container.config.clip_upload_verdict_timeout_s.from_value(config.CLIP_UPLOAD_VERDICT_TIMEOUT_S)
container.wire(modules=[routes])


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Cargando modelo YOLO y extractor de features (192-dim)...")
    container.pose_estimator()
    container.feature_extractor()
    container.redis_client()
    # DEF-16: barrido periódico que libera las MatchSession cerradas hace
    # más de SESSION_TTL_S (ver SessionRegistry.sweep_forever).
    sweep_task = asyncio.create_task(
        container.sessions().sweep_forever(
            config.SESSION_TTL_S, config.SESSION_SWEEP_INTERVAL_S
        )
    )
    log.info("Fog listo.")
    yield
    sweep_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sweep_task
    await container.redis_client().close()


app = FastAPI(
    title="SABRE.AI — Fog Service",
    description=(
        "Gateway WebRTC + extracción de features biomecánicas para el "
        "sistema de video-arbitraje IA de esgrima sable (pipeline "
        "lstm_6class: 192 features, 6 clases, luz Favero como filtro y, "
        "según el checkpoint, también como input del modelo). "
        "Ver CONTRATO_API.md y PLAN_ARQUITECTURA_DDD.md para el contrato "
        "completo con Edge y Cloud."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(routes.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)