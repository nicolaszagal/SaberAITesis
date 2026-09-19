# Imagen de Cloud (worker: consume Redis Streams, corre el LSTM, publica
# veredicto). Sin servidor HTTP — en Render, desplegar como "Background
# Worker", NO como "Web Service" (Render espera que un Web Service abra un
# puerto HTTP para su health check; Cloud no expone ninguno — ver
# https://render.com/docs/background-workers).
FROM python:3.12-slim

WORKDIR /app/backend

# El checkpoint vive en backend/dataset/lstm_4class/checkpoints/best_model.pt
# (556 KB, comiteado en este repo — a diferencia de dataset/yolov8x-pose.pt
# de Fog, 133 MB, que se queda afuera del repo y se monta como volumen).
# Build remoto (Render clona el repo de GitHub): solo ve lo que está
# comiteado, así que el checkpoint tiene que estar en el repo para que este
# COPY funcione — confirmar con `git status` que
# backend/dataset/lstm_4class/checkpoints/best_model.pt está agregado y
# pusheado antes de desplegar.
ENV LSTM_CHECKPOINT_PATH=/app/backend/dataset/lstm_4class/checkpoints/best_model.pt

COPY requirements-cloud.txt .

# torch CPU-only: el modelo LSTM desplegado es chico (hidden_size=64,
# 1 capa, ver shared/config.py) y no necesita GPU.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements-cloud.txt

COPY cloud/ cloud/
COPY shared/ shared/
COPY dataset/lstm_4class/checkpoints/best_model.pt dataset/lstm_4class/checkpoints/best_model.pt

CMD ["python", "-m", "cloud.main"]
