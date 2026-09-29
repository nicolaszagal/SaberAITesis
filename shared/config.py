"""Configuración compartida entre Fog y Cloud. Todo override-able por env var.

Features de Fog: 192 por frame, idénticas a dataset/05_extract_features.py;
recorte y ablación por versión de modelo (FEATURE_PREPROCESSING_PROFILE).
Cloud despliega el pipeline de 6 clases (DEF-03 resuelto): hiperparámetros
del LSTM en `run_config.json` dentro de MODEL_RUN_DIR, no en este módulo.
"""

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Base PostgreSQL de Fog (esquema `sabre`, ver docs_claude/sabre_ai_schema.sql).
# Formato SQLAlchemy async: postgresql+asyncpg://usuario:clave@host:5432/base.
# Sin default a propósito: la URL lleva credenciales, no se versionan. Se
# valida al construir el engine (ver fog/infrastructure/persistence/database.py).
DATABASE_URL = os.environ.get("DATABASE_URL")

# Directorio raíz del almacenamiento local de archivos (clips y keypoints
# .npz por SHA-256). En Docker es el volumen montado en /data/storage.
# La base solo guarda URI y hash de estos archivos. Sin default, igual que
# DATABASE_URL: el adaptador se construye recién cuando se necesita.
STORAGE_DIR = os.environ.get("STORAGE_DIR")

# Fog -> Cloud
STREAM_FEATURES = "fog:features"
GROUP_CLOUD = "cloud_workers"
CONSUMER_CLOUD = os.environ.get("CLOUD_CONSUMER_NAME", "cloud-worker-1")

# Dead-letter de fog:features: entradas que RedisFeatureConsumer no pudo
# parsear (campo faltante, shape/dtype/tamaño de buffer inconsistente),
# con el motivo agregado. Ver CONTRATO_API.md sección 5 y DEF-09.
STREAM_FEATURES_DEAD = "fog:features:dead"

# Tiempo mínimo que una entrada debe estar pendiente (sin ACK) en el grupo
# de consumidores antes de que Cloud la reclame con XAUTOCLAIM al arrancar
# (worker anterior que murió entre XREADGROUP y XACK). Ver DEF-09.
CLAIM_MIN_IDLE_S = float(os.environ.get("CLAIM_MIN_IDLE_S", "60.0"))

# Cloud -> Fog (un stream por revision_id)
VERDICT_STREAM_PREFIX = "cloud:verdicts:"

# Modelo de pose (YOLOv8x-pose, igual que dataset/05_extract_features.py --model x)
YOLO_POSE_MODEL_PATH = os.environ.get(
    "YOLO_POSE_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "dataset", "yolov8x-pose.pt"),
)

# Directorio de la corrida del modelo LSTM desplegado (DEF-03): apunta a
# dataset/lstm_6class/checkpoints/<run_id>/, que contiene run_config.json
# (hiperparámetros: hidden_size, num_layers, dropout, luz_size, use_attention,
# n_classes, classes) y el checkpoint (ver
# cloud/infrastructure/classifier/lstm6class_adapter.py, CHECKPOINT_FILENAME).
# El run_id vigente puede cambiar tras un diagnóstico en curso — no se fija
# nada del run en el código, todo por esta variable (contexto_sabre.md
# sección 8).
#
# Sin default (DEF-15): Cloud debe fijar esta variable explícitamente con
# la ubicación vigente del checkpoint (ver require_paths() más abajo y
# GUIA_EJECUCION.md).
MODEL_RUN_DIR = os.environ.get("MODEL_RUN_DIR")

# Estadísticas de estandarización (mean/std, shape (192,), calculadas solo
# sobre train) — ver dataset/lstm_4class/compute_stats.py. FeatureExtractorPort
# en Fog las usa para replicar el preprocesamiento de entrenamiento.
#
# Sin default (DEF-15): antes apuntaba a dataset/lstm_4class/feature_stats.npz,
# que ya no existe en este repo. Fog debe fijar esta variable explícitamente
# con la ubicación vigente (ver require_paths() más abajo y GUIA_EJECUCION.md).
FEATURE_STATS_PATH = os.environ.get("FEATURE_STATS_PATH")

# Preprocesamiento de features por versión de modelo (recorte ±kσ y ablación
# de columnas): nombre del perfil definido en
# fog/infrastructure/features/preprocessing_profiles.json (o en el archivo de
# FEATURE_PREPROCESSING_PROFILES_PATH). Sin default: debe coincidir con el
# checkpoint y las estadísticas desplegadas (ver require_paths()).
FEATURE_PREPROCESSING_PROFILE = os.environ.get("FEATURE_PREPROCESSING_PROFILE")
FEATURE_PREPROCESSING_PROFILES_PATH = os.environ.get("FEATURE_PREPROCESSING_PROFILES_PATH")

MIN_FRAMES = 3

# Tamaño máximo aceptado para POST /matches/{match_id}/clip (DEF-13): un
# archivo por encima de este límite se rechaza con 413 antes de escribirlo
# a disco. Ver fog/infrastructure/clips/clip_file_reader.py.
CLIP_MAX_MB = float(os.environ.get("CLIP_MAX_MB", "200"))

# Tiempo que Fog espera la señal de luz Favero (POST /webrtc/{match_id}/luz)
# después de que termina el clip, antes de procesar con LuzSignal.none().
# Ver PLAN_ARQUITECTURA_DDD.md sección 2.3.
FAVERO_LUZ_TIMEOUT_S = float(os.environ.get("FAVERO_LUZ_TIMEOUT_S", "2.0"))

# Tiempo que POST /matches/{match_id}/clip espera el veredicto de Cloud
# (Redis "cloud:verdicts:{match_id}") antes de responder con timed_out=True.
# Pipeline completo (pose+tracking+features+Redis+LSTM), no solo la espera
# corta de la luz Favero — default más generoso que FAVERO_LUZ_TIMEOUT_S.
CLIP_UPLOAD_VERDICT_TIMEOUT_S = float(os.environ.get("CLIP_UPLOAD_VERDICT_TIMEOUT_S", "30.0"))

# Tiempo que SessionRegistry mantiene una sesión (MatchSession) después de
# entregar el veredicto o el "no disponible", antes de liberarla (DEF-16):
# ventana para aceptar conexiones tardías de GET /ws/veredicto/{match_id}
# que todavía no llegaron cuando el resultado quedó listo.
SESSION_TTL_S = float(os.environ.get("SESSION_TTL_S", "120.0"))

# Cada cuánto corre el barrido periódico que libera las sesiones vencidas
# (más viejas que SESSION_TTL_S desde que se cerraron). No es un requisito
# funcional, solo la cadencia del housekeeping — igual que CLAIM_MIN_IDLE_S
# más arriba.
SESSION_SWEEP_INTERVAL_S = float(os.environ.get("SESSION_SWEEP_INTERVAL_S", "30.0"))

# TTL (segundos) del stream Redis "cloud:verdicts:{match_id}": Cloud lo fija
# con EXPIRE en cada XADD (DEF-16) para que un match_id sin consumidor no
# quede acumulando memoria en Redis indefinidamente.
VERDICT_STREAM_TTL_S = int(os.environ.get("VERDICT_STREAM_TTL_S", "3600"))

# Mapeo fijo v1, confirmado por Nicolas: A=ROJ (izquierda en cámara), B=VER (derecha).
FENCER_COLOR = {"A": "ROJ", "B": "VER"}


def require_paths(*names: str) -> None:
    """Falla con un mensaje explícito si alguna ruta requerida no está seteada.

    dataset/lstm_4class/ ya no existe en este repo (DEF-15), así que
    MODEL_RUN_DIR y FEATURE_STATS_PATH quedaron sin valor por
    defecto: hay que fijarlas por variable de entorno con la ubicación
    vigente del modelo. Fog y Cloud llaman a esta función al arrancar,
    antes de construir su Container, para fallar con un mensaje claro en
    vez de un FileNotFoundError opaco dentro de torch.load/np.load.

    Args:
        names: nombres de variables de este módulo a validar (por ejemplo
            "MODEL_RUN_DIR").

    Raises:
        RuntimeError: si alguna de las variables nombradas es None,
            listando cuáles faltan.
    """
    missing = [name for name in names if not globals().get(name)]
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno requeridas: "
            + ", ".join(missing)
            + ". dataset/lstm_4class/ ya no existe (DEF-15); no hay ruta por "
            "defecto para el modelo. Fijar cada variable con la ruta del "
            "archivo vigente antes de arrancar (ver GUIA_EJECUCION.md)."
        )
