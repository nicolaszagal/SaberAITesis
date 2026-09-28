# Imagen de Fog (API Gateway WebRTC + extracción de pose/features).
#
# IMPORTANTE — networking: aiortc elige sus puertos UDP de ICE al azar (el
# propio sistema operativo, no aiortc/aioice — confirmado por el maintainer
# de aiortc en https://github.com/aiortc/aiortc/issues/487: "you cannot
# limit the UDP ports used by ICE"). Por eso este contenedor necesita
# correr con red de host (`network_mode: host` en fog/docker-compose.yml)
# para que esos puertos sean alcanzables — con red puente normal de Docker,
# el cliente WebRTC del front no podría conectar. En Docker Desktop para
# Mac, red de host requiere habilitar el toggle beta "Enable host
# networking" (Settings > Resources > Network, Docker Desktop >= 4.34,
# requiere desactivar Enhanced Container Isolation y reiniciar Docker
# Desktop) y no es soporte oficial fuera de Linux — ver GUIA_EJECUCION.md
# sección Docker para el detalle y el fallback a venv si resulta inestable.
FROM python:3.12-slim

WORKDIR /app/backend

# Rutas por defecto de shared/config.py (dos niveles arriba de shared/)
# resolverían a /app/dataset/... igual que en el host de Nicolas (sibling
# de backend/). Las fijamos explícitas para no depender de esa cuenta de
# directorios dentro del contenedor.
ENV YOLO_POSE_MODEL_PATH=/app/dataset/yolov8x-pose.pt
ENV FEATURE_STATS_PATH=/app/dataset/lstm_4class/feature_stats.npz

# Librerías nativas requeridas por opencv-python (libGL, libglib, etc.) en
# una imagen "slim" sin X server — causa típica de
# "ImportError: libGL.so.1: cannot open shared object file" al importar cv2
# en imágenes Debian minimalistas. Si aiortc/av lanzan algún ImportError de
# librería nativa al correr, ese es el próximo apt-get a agregar (no hay
# evidencia de que lo necesiten: sus wheels manylinux suelen traer su
# ffmpeg/SRTP estático).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-fog.txt constraints.txt ./

# torch + torchvision CPU-only vía el índice oficial (ultralytics requiere
# ambos de transitivo) — mismo criterio que GUIA_EJECUCION.md sección 2
# para venv. -c constraints.txt fija las versiones verificadas juntas
# (DEF-19; ver constraints.txt) tanto acá como en el install de
# requirements-fog.txt de abajo, para que ultralytics no resuelva una
# versión distinta a la usada en desarrollo. Si la máquina que corre esta
# imagen tiene GPU NVIDIA y querés usarla acá, cambiar este índice por el
# de CUDA correspondiente (https://pytorch.org/get-started/locally/) y
# reconstruir la imagen.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu -c constraints.txt
RUN pip install --no-cache-dir -r requirements-fog.txt -c constraints.txt

COPY fog/ fog/
COPY shared/ shared/

EXPOSE 8001

CMD ["uvicorn", "fog.main:app", "--host", "0.0.0.0", "--port", "8001"]
