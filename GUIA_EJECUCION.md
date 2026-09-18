# Guía de ejecución — Backend SABRE.AI

## 1. Requisitos previos

- Python 3.10+ (verificado con 3.10).
- Redis corriendo y accesible (broker entre Fog y Cloud). Sin Redis, ni Fog ni
  Cloud arrancan.
- `dataset/yolov8x-pose.pt`, `dataset/lstm_4class/checkpoints/best_model.pt` y
  `dataset/lstm_4class/feature_stats.npz` presentes en el repo (rutas por
  defecto en `shared/config.py`, todas override-ables por env var).

## 2. Instalación

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# torch primero, siguiendo https://pytorch.org/get-started/locally/
# según tu plataforma (CPU/CUDA/MPS) — no incluido en requirements.txt
# porque el wheel correcto depende del hardware.
pip install torch

pip install -r requirements.txt
```

`ultralytics` no tiene versión pinneada en `requirements.txt` (no se pudo
verificar en el entorno donde se construyó este backend). Si ya tenés una
versión fijada para `dataset/lstm_4class/05_extract_features.py`, usar esa
misma para evitar divergencias de comportamiento entre tracking de
entrenamiento y producción.

### Si `pip install -r requirements.txt` intenta compilar algo desde un `.tar.gz`

Normalmente significa que PyPI no tiene wheel precompilado para tu
combinación de Python + SO (frecuente con versiones de Python muy nuevas) y
pip cae a compilar desde código fuente, lo cual falla sin un toolchain de
C/Fortran/meson instalado. Alcanza con: (a) actualizar pip
(`python -m pip install --upgrade pip`), o (b) usar una versión de Python
algo más madura (3.12/3.13) con más wheels publicados. Ver el comentario
sobre `numpy==2.3.4` en `requirements.txt` para un caso concreto ya resuelto.

## 3. Variables de entorno (todas opcionales, ver `shared/config.py`)

| variable                | default                                         | uso |
|-------------------------|-------------------------------------------------|-----|
| `REDIS_URL`             | `redis://localhost:6379/0`                      | conexión Fog y Cloud |
| `YOLO_POSE_MODEL_PATH`  | `dataset/yolov8x-pose.pt`                       | modelo de pose (Fog) |
| `LSTM_CHECKPOINT_PATH`  | `dataset/lstm_4class/checkpoints/best_model.pt` | checkpoint LSTM (Cloud) |
| `FEATURE_STATS_PATH`    | `dataset/lstm_4class/feature_stats.npz`         | mean/std de estandarización (Fog) |
| `FAVERO_LUZ_TIMEOUT_S`  | `2.0`                                           | espera máxima de la luz Favero antes de clasificar sin ella |
| `CLOUD_CONSUMER_NAME`   | `cloud-worker-1`                                | nombre de consumidor en el grupo `cloud_workers` (relevante si se levanta más de una instancia de Cloud) |

## 4. Levantar los servicios

Cloud y Fog son procesos independientes; ambos requieren Redis arriba.

```bash
# Terminal 1 — Cloud (consumidor + clasificador)
cd backend
python -m cloud.main

# Terminal 2 — Fog (API Gateway WebRTC)
cd backend
python -m uvicorn fog.main:app --host 0.0.0.0 --port 8001
```

Si `python -m cloud.main` falla con `redis.exceptions.ConnectionError`,
es porque Redis no está corriendo — confirmar el prerequisito de la sección 1
(`redis-server` o el contenedor equivalente) antes de levantar Cloud o Fog.

Swagger UI de Fog: `http://localhost:8001/docs` (generado automáticamente por
FastAPI a partir de `fog/infrastructure/api/routes.py` y
`fog/infrastructure/api/schemas.py`). El WebSocket (`/ws/veredicto/{match_id}`)
no aparece ahí porque OpenAPI no documenta WebSockets — el contrato de sus
mensajes está en `CONTRATO_API.md` sección 6.

Cloud no expone HTTP; es un loop de consumo de Redis (`python -m cloud.main`)
sin servidor.

Edge (captura RTSP de los iPhones → WebSocket para el front) es un tercer
servicio independiente, solo necesario si estás probando con video real de
las cámaras — Fog/Cloud no dependen de él. Ver sección 6.4.

## 5. Tests

```bash
cd backend
python3 -m pytest tests/ -v
```

28 tests, todos con fakes (sin Redis, sin modelos reales, sin
`ultralytics` instalado) — cubren `application/` de Fog y Cloud,
`InMemoryMatchRepository`, `New192FeatureExtractor`, `try_lock_ids` y
`FaveroHardMaskPolicy`. `LSTM4ClassAdapter` se prueba con un checkpoint
sintético (misma arquitectura, pesos aleatorios) para no depender del
checkpoint real de producción en un test unitario.

No cubierto por estos tests (pendiente, ver tarea "Smoke test end-to-end"):
`YoloV8PoseAdapter` (requiere `ultralytics` + modelo real) y el flujo
completo WebRTC -> Redis -> Cloud -> WebSocket con un clip real del dataset.

## 6. Docker

Fog y Cloud tienen imágenes separadas (`Dockerfile.fog`, `Dockerfile.cloud`)
porque casi no comparten dependencias: Cloud es un worker puro (Redis +
torch, sin FastAPI/aiortc/opencv/ultralytics — ver `requirements-cloud.txt`
vs `requirements-fog.txt`).

### 6.1 Fog, local

```bash
cd backend
cp .env.example .env   # completar REDIS_URL (ver 6.3)
docker compose build fog
docker compose up fog
```

Requiere `dataset/` como sibling de `backend/` en tu filesystem (mismo
layout que la sección 1 y que le pedimos replicar a Carlos) — se monta
como volumen de solo lectura, no se hornea en la imagen.

**Mac: WebRTC en Docker.** aiortc elige sus puertos UDP de ICE al azar (no
se pueden fijar a un rango — confirmado por el maintainer de aiortc en
[aiortc/aiortc#487](https://github.com/aiortc/aiortc/issues/487)), así que
el contenedor de Fog necesita `network_mode: host` (ya seteado en
`docker-compose.yml`) para que esos puertos sean alcanzables. Docker
Desktop para Mac no soporta red de host de forma estable: hay un toggle
beta desde la versión 4.34 (Settings > Resources > Network > **Enable host
networking**; requiere haber iniciado sesión, desactivar *Enhanced
Container Isolation*, y reiniciar Docker Desktop) pero la comunidad reporta
inestabilidad. Si falla la conexión WebRTC con esto activado, el fallback
es correr Fog con venv (sección 2) en vez de Docker — el endpoint de subir
clip (`/matches/{match_id}/clip`) no usa WebRTC y funciona en Docker en Mac
sin esto.

### 6.2 Cloud, Render

Antes de desplegar, confirmar que el checkpoint está comiteado y pusheado:

```bash
git status backend/dataset/lstm_4class/checkpoints/best_model.pt
```

Render solo ve lo que está en el repo de GitHub, no tu filesystem local —
a diferencia de `dataset/yolov8x-pose.pt` (133 MB, de Fog), este checkpoint
(556 KB) sí está pensado para vivir en el repo de `backend/`.

En Render: **New > Background Worker** (no *Web Service* — Cloud no expone
HTTP, y un Web Service espera que algún puerto responda al health check).
Conectar el repo de GitHub y configurar:

- **Dockerfile Path**: `Dockerfile.cloud`
- **Root Directory**: vacío (el repo de GitHub que clonó Carlos ya es la
  raíz que contiene `Dockerfile.cloud`)
- Variable de entorno `REDIS_URL`: la misma URL de Upstash que usa Fog
  (sección 6.3)

### 6.3 Redis entre Fog (local) y Cloud (remoto)

Con Fog corriendo en tu máquina y Cloud en Render, ambos necesitan ver el
mismo Redis por internet. Comparé dos opciones (verificado en su
documentación, no por defecto del SDK):

- **Redis Key Value de Render**: requiere agregar tu IP a una allowlist
  para habilitar la URL externa — se rompe si tu IP cambia (típico en
  conexión residencial) o si corrés Fog desde otra red.
- **Upstash**: por defecto acepta conexiones desde cualquier IP (solo
  usuario/password + TLS, sin allowlist que mantener) — recomendado por
  eso para este caso, donde Fog no corre siempre desde la misma red.

`REDIS_URL` queda igual en ambos lados: `rediss://default:PASSWORD@HOST.upstash.io:PORT`
(mismo formato que ya usan `fog/composition.py` y `cloud/composition.py`
vía `redis.from_url`).

### 6.4 Edge, local (Docker) — captura RTSP → WebSocket

Servicio independiente de Fog/Cloud: redistribuye el video de las dos
cámaras como frames JPEG por WebSocket al front. No hace pose, features ni
inferencia — eso sigue siendo trabajo de Fog/Cloud.

```
iPhone (Larix, RTMP) → mediamtx (RTSP) → edge/ (bridge WS) → front
```

**Requisitos:** dos iPhones con Larix Broadcaster (u otra app RTMP) en la
misma red que la máquina que corre `mediamtx`, publicando a
`rtmp://<IP de esa máquina>:1935/live/front` y `.../live/top`. Solo Docker
— `mediamtx` no tiene instalación por venv, se usa la imagen oficial.

```bash
cd backend/edge
cp .env.example .env   # completar si el RTSP no corre en localhost:8554
```

| variable          | default (`.env.example`)                          | requerida | uso |
|--------------------|-----------------------------------------------------|-----------|-----|
| `RTSP_FRONT_URL`   | `rtsp://host.docker.internal:8554/live/front`        | sí        | URL RTSP de la cámara "front" servida por mediamtx |
| `RTSP_TOP_URL`     | `rtsp://host.docker.internal:8554/live/top`          | sí        | URL RTSP de la cámara "top" |
| `WS_PORT`          | `8001`                                               | no        | puerto del servidor WebSocket |
| `JPEG_QUALITY`     | `70`                                                 | no        | calidad de codificación JPEG (0-100) |
| `TARGET_FPS`       | `15`                                                 | no        | framerate de redistribución hacia los clientes WS |

Sin `RTSP_FRONT_URL`/`RTSP_TOP_URL` el proceso falla al arrancar con
`KeyError` — comportamiento esperado (falla rápido en vez de arrancar mal
configurado).

Levantar (perfil `local`, separado de `localdev`: este requiere las
cámaras físicas conectadas, no solo Fog/Cloud):

```bash
cd backend
docker compose --profile local up mediamtx edge
```

Verificar:

- **mediamtx** recibiendo el RTMP de los iPhones: sus logs deberían
  mostrar la conexión entrante en `:1935`.
- **edge** sirviendo WebSocket: conectarse a `ws://localhost:8001/front` o
  `ws://localhost:8001/top` (un mensaje binario JPEG por frame). Un GET
  HTTP plano a `http://localhost:8001/` responde `426 Upgrade Required`
  — es el comportamiento esperado del healthcheck del compose, no un error.
- **Reconexión:** si se corta la señal de un iPhone, los logs de `edge`
  muestran `Stream perdido, reconectando en Xs...` (backoff 1s→2s→4s→8s)
  y `Stream restaurado` al recuperarse — no hace falta reiniciar el
  contenedor.

## 7. Limitaciones conocidas de esta entrega

- Sin CI configurado (decisión explícita: tests corren manualmente).
- `MatchRepositoryPort` solo tiene implementación en memoria
  (`InMemoryMatchRepository`) — no persiste entre restarts de Fog.
- Sin integración física con la luz Favero real; el front debe simularla y
  reportarla vía `POST /webrtc/{match_id}/luz` (ver `CONTRATO_API.md`).
- Smoke test end-to-end con clip real del dataset todavía pendiente.
- Edge no tiene tests automatizados ni conexión con Fog/Cloud (solo
  redistribuye video crudo al front); su healthcheck de Docker verifica
  que el servidor WebSocket responda, no que las cámaras RTSP estén
  conectadas — para eso hay que mirar los logs (ver sección 6.4).
