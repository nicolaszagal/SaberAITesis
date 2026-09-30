# Imagen de Fog (API de la Validación 1: carga de clip, pose, features y
# persistencia). Autocontenida: no monta dataset/ en el uso normal.
#
# Red: en la Validación 1 no se usa WebRTC (docs_claude/contexto_sabre.md
# sección 8), así que Fog corre en red puente con el puerto 8001 publicado.
# La red de host solo haría falta para un posible perfil v2 con WebRTC
# (aiortc elige al azar sus puertos UDP de ICE, aiortc/aiortc#487).
FROM python:3.12-slim

WORKDIR /app/backend

# Run del modelo desplegado: lo usa el entrypoint para registrarlo si no hay
# una versión activa (scripts/registrar_modelo.py). Se cambia con
# --build-arg RUN_ID=<run_id>.
ARG RUN_ID=20260928_141021
ENV MODEL_RUN_ID=${RUN_ID}

# Rutas dentro de la imagen. Son las de shared/config.py y de
# scripts/registrar_modelo.py (dataset/ como hermano de backend/, en /app).
ENV YOLO_POSE_MODEL_PATH=/app/dataset/yolov8x-pose.pt
ENV FEATURE_STATS_PATH=/app/dataset/lstm_6class/feature_stats.npz
# Perfil de recorte/ablación del modelo (fog/infrastructure/features/preprocessing_profiles.json).
ENV FEATURE_PREPROCESSING_PROFILE=lstm_6class
# Ultralytics escribe su configuración aquí (el directorio por defecto no es escribible).
ENV YOLO_CONFIG_DIR=/tmp/Ultralytics

# Librerías nativas de opencv-python en una imagen "slim" sin X server.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-fog.txt constraints.txt ./

# torch + torchvision CPU-only desde el índice oficial; -c constraints.txt
# fija las versiones verificadas juntas (DEF-19).
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu -c constraints.txt
RUN pip install --no-cache-dir -r requirements-fog.txt -c constraints.txt

# Pesos de pose YOLOv8x (133 MB, no se comitean). Se descargan de la release
# oficial de Ultralytics y el build falla si el SHA-256 no coincide con el del
# archivo usado en el entrenamiento (Software/dataset/yolov8x-pose.pt).
ARG YOLO_POSE_URL=https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8x-pose.pt
ARG YOLO_POSE_SHA256=7a9bf952c2fc1c07d4a1da00dbb4cfab5ed71f89cbe8824d51a8f7a61cee5825
RUN mkdir -p /app/dataset && python - <<PY
import hashlib, urllib.request
destino = "/app/dataset/yolov8x-pose.pt"
urllib.request.urlretrieve("${YOLO_POSE_URL}", destino)
h = hashlib.sha256(open(destino, "rb").read()).hexdigest()
if h != "${YOLO_POSE_SHA256}":
    raise SystemExit(f"SHA-256 de yolov8x-pose.pt no coincide: {h}")
print("yolov8x-pose.pt verificado", h)
PY

# Artefactos pequeños del modelo desplegado (comiteados en backend/dataset/).
COPY dataset/lstm_6class/ /app/dataset/lstm_6class/

COPY fog/ fog/
COPY shared/ shared/
COPY scripts/ scripts/
COPY alembic.ini .

RUN chmod +x fog/docker-entrypoint.sh

EXPOSE 8001

# Aplica las migraciones, registra el modelo si no hay uno activo y arranca
# uvicorn (ver fog/docker-entrypoint.sh).
ENTRYPOINT ["fog/docker-entrypoint.sh"]
