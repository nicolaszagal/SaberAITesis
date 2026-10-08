# Imagen de Cloud (worker: consume Redis Streams, corre el LSTM, publica
# veredicto). Sin servidor HTTP — en Render, desplegar como "Background
# Worker", NO como "Web Service" (Render espera que un Web Service abra un
# puerto HTTP para su health check; Cloud no expone ninguno — ver
# https://render.com/docs/background-workers).
FROM python:3.12-slim

WORKDIR /app/backend

# El run del checkpoint desplegado vive en
# backend/dataset/lstm_6class/checkpoints/<run_id>/ (run_config.json +
# best_model.pt, unos cientos de KB, comiteado en este repo — a diferencia
# de yolov8x-pose.pt de Fog, 133 MB, que se descarga en el build de Fog).
# El run_id vigente puede cambiar tras un
# diagnóstico en curso (docs_claude/contexto_sabre.md sección 8): no se fija
# en el código, se pasa como build arg (`--build-arg RUN_ID=<run_id>`).
# Build remoto (Render clona el repo de GitHub): solo ve lo que está
# comiteado, así que el run tiene que estar en el repo para que el COPY de
# abajo funcione — confirmar con `git status` que
# backend/dataset/lstm_6class/checkpoints/<run_id>/ está agregado y pusheado
# antes de desplegar.
ARG RUN_ID=20260928_141021
ENV MODEL_RUN_DIR=/app/backend/dataset/lstm_6class/checkpoints/${RUN_ID}

COPY requirements-cloud.txt constraints.txt ./

# torch + torchvision CPU-only: el modelo LSTM desplegado es chico
# (hidden_size=64, 1 capa, ver shared/config.py) y no necesita GPU.
# torchvision no lo usa el código de Cloud, pero se instala junto a torch
# con la misma versión fijada en constraints.txt (DEF-19) que en Fog, para
# no divergir de las versiones verificadas juntas en backend/.venv.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu -c constraints.txt
RUN pip install --no-cache-dir -r requirements-cloud.txt -c constraints.txt

COPY cloud/ cloud/
COPY shared/ shared/
COPY dataset/lstm_6class/checkpoints/${RUN_ID}/run_config.json dataset/lstm_6class/checkpoints/${RUN_ID}/run_config.json
COPY dataset/lstm_6class/checkpoints/${RUN_ID}/best_model.pt dataset/lstm_6class/checkpoints/${RUN_ID}/best_model.pt

COPY cloud/docker-entrypoint.sh /usr/local/bin/sabre-cloud-entrypoint.sh

# Usuario no root (DEPLOY05). Cloud solo lee el checkpoint y habla con Redis.
RUN useradd --system --uid 10001 --create-home sabre
USER sabre

ENTRYPOINT ["sh", "/usr/local/bin/sabre-cloud-entrypoint.sh"]
CMD ["python", "-m", "cloud.main"]
