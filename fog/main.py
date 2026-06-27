"""
Fog — API Gateway (FastAPI) + WebRTC (aiortc) + cliente Redis Streams.

Responsabilidades (ver ../CONTRATO_API.md):
  1. POST /matches/config — paso previo opcional: genera match_id y fija
     weapon_side_A/B antes de que llegue el video.
  2. POST /webrtc/offer — recibe oferta SDP + config de combate del front
     (Edge), arma la pista de video, devuelve la respuesta SDP.
  3. POST /webrtc/{match_id}/luz — recibe la señal de luz Favero (RJ11,
     fuera de alcance de este backend) antes de que termine el clip.
  4. POST /matches/{match_id}/clip — alternativa a 2+3 para subir un clip
     ya grabado (sin WebRTC) junto con los frames de señal Favero;
     responde con el veredicto de forma síncrona.
  5. Procesa los frames del clip (WebRTC o subido) frame a frame en
     cuanto llegan (PoseTrackingSession, ver ports/pose_estimator.py) y
     extrae features 192-dim al finalizar (FeatureExtractorPort, pipeline
     lstm_4class).
  6. Publica las features en el stream Redis "fog:features" para Cloud.
  7. Escucha el stream de veredicto de Cloud ("cloud:verdicts:{match_id}")
     y lo reenvía al front por WebSocket (/ws/veredicto/{match_id}).

Arquitectura DDD/hexagonal: domain/, ports/, application/, infrastructure/
(ver PLAN_ARQUITECTURA_DDD.md). Este archivo solo ensambla el Container
(composition.py) y expone la app FastAPI — no contiene lógica de negocio.

Ejecutar (desde backend/):
    uvicorn fog.main:app --host 0.0.0.0 --port 8001
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fog.composition import Container
from fog.infrastructure.api import routes
from shared import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("fog")

# Diagnostico temporal: ver que par de candidatos ICE selecciona aiortc para
# la conexion real con el cliente (¿loopback 127.0.0.1, o la interfaz Wi-Fi
# del host?). Si selecciona Wi-Fi, cada paquete de medios sale y vuelve por
# el adaptador de red en vez de loopback, lo cual puede ser muchisimo mas
# lento. Quitar una vez confirmado/descartado.
logging.getLogger("aioice.ice").setLevel(logging.DEBUG)

container = Container()
container.config.redis_url.from_value(config.REDIS_URL)
container.config.yolo_pose_model_path.from_value(config.YOLO_POSE_MODEL_PATH)
container.config.feature_stats_path.from_value(config.FEATURE_STATS_PATH)
container.config.ablate_indices.from_value(config.ABLATE_INDICES)
container.config.min_frames.from_value(config.MIN_FRAMES)
container.config.luz_timeout_s.from_value(config.FAVERO_LUZ_TIMEOUT_S)
container.config.clip_upload_verdict_timeout_s.from_value(config.CLIP_UPLOAD_VERDICT_TIMEOUT_S)
container.wire(modules=[routes])


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Cargando modelo YOLO y extractor de features (lstm_4class, 192-dim)...")
    container.pose_estimator()
    container.feature_extractor()
    container.redis_client()
    log.info("Fog listo.")
    yield
    await container.redis_client().close()


app = FastAPI(
    title="SABRE.AI — Fog Service",
    description=(
        "Gateway WebRTC + extracción de features biomecánicas para el "
        "sistema de video-arbitraje IA de esgrima sable (pipeline "
        "lstm_4class: 192 features, 4 clases, luz Favero como input). "
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