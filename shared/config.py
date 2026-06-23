"""Configuración compartida entre Fog y Cloud. Todo override-able por env var.

Pipeline desplegado: lstm_4class (192 features, 4 clases, luz Favero como
input del modelo, attention pooling). El pipeline anterior (182 features,
6 clases, sin luz) quedó descartado — ver PLAN_ARQUITECTURA_DDD.md.
"""

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Fog -> Cloud
STREAM_FEATURES = "fog:features"
GROUP_CLOUD = "cloud_workers"
CONSUMER_CLOUD = os.environ.get("CLOUD_CONSUMER_NAME", "cloud-worker-1")

# Cloud -> Fog (un stream por match_id)
VERDICT_STREAM_PREFIX = "cloud:verdicts:"

# Modelo de pose (YOLOv8x-pose, igual que dataset/05_extract_features.py --model x)
YOLO_POSE_MODEL_PATH = os.environ.get(
    "YOLO_POSE_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "dataset", "yolov8x-pose.pt"),
)

# Checkpoint del modelo LSTM desplegado (lstm_4class: 4 clases, 192 features,
# luz Favero, attention). Seleccionado por val loss — ver PLAN_ARQUITECTURA_DDD.md.
LSTM_CHECKPOINT_PATH = os.environ.get(
    "LSTM_CHECKPOINT_PATH",
    os.path.join(
        os.path.dirname(__file__), "..", "..", "dataset", "lstm_4class", "checkpoints", "best_model.pt"
    ),
)

# Estadísticas de estandarización (mean/std, shape (192,), calculadas solo
# sobre train) — ver dataset/lstm_4class/compute_stats.py. FeatureExtractorPort
# en Fog las usa para replicar el preprocesamiento de entrenamiento.
FEATURE_STATS_PATH = os.environ.get(
    "FEATURE_STATS_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "dataset", "lstm_4class", "feature_stats.npz"),
)

LSTM_HIDDEN_SIZE = 64
LSTM_NUM_LAYERS = 1
LSTM_NUM_CLASSES = 4
LUZ_SIZE = 2
USE_ATTENTION = True

# Ablación diagnóstica de Fase B (vel_elbow_angle de A y B) — el checkpoint
# desplegado se entrenó y evaluó con estas columnas en 0 (ver
# dataset/lstm_4class/lstm_dataset.py, ABLATE_INDICES). Replicarla en
# producción es necesaria para igualar la accuracy documentada.
ABLATE_INDICES = [95, 191]

MIN_FRAMES = 3

# Tiempo que Fog espera la señal de luz Favero (POST /webrtc/{match_id}/luz)
# después de que termina el clip, antes de procesar con LuzSignal.none().
# Ver PLAN_ARQUITECTURA_DDD.md sección 2.3.
FAVERO_LUZ_TIMEOUT_S = float(os.environ.get("FAVERO_LUZ_TIMEOUT_S", "2.0"))

# Tiempo que POST /matches/{match_id}/clip espera el veredicto de Cloud
# (Redis "cloud:verdicts:{match_id}") antes de responder con timed_out=True.
# Pipeline completo (pose+tracking+features+Redis+LSTM), no solo la espera
# corta de la luz Favero — default más generoso que FAVERO_LUZ_TIMEOUT_S.
CLIP_UPLOAD_VERDICT_TIMEOUT_S = float(os.environ.get("CLIP_UPLOAD_VERDICT_TIMEOUT_S", "30.0"))

# Mapeo fijo v1, confirmado por Nicolas: A=ROJ (izquierda en cámara), B=VER (derecha).
FENCER_COLOR = {"A": "ROJ", "B": "VER"}
