# Guía de ejecución — Backend SABRE.AI

## 1. Requisitos previos

- Python 3.10+ (verificado con 3.10 y 3.14; las imágenes Docker usan 3.12).
- Redis corriendo y accesible (broker entre Fog y Cloud). Sin Redis, ni Fog ni
  Cloud arrancan.
- PostgreSQL 16 con el esquema `sabre` migrado (sección 6.1): registra clips, tocados,
  clasificaciones, veredictos y la auditoría. Sin `DATABASE_URL`, Fog arranca pero las rutas
  con persistencia responden 500 (incluido `/health`).
- Directorios de trabajo de Fog: `STORAGE_DIR` (clips y keypoints) y `EVIDENCE_DIR` (log y
  exportación de evidencia); ver la tabla de la sección 3.
- `dataset/yolov8x-pose.pt` presente en el repo (ruta por defecto en
  `shared/config.py`, override-able con `YOLO_POSE_MODEL_PATH`).
- **Variables de entorno obligatorias, sin default (DEF-15):**
  `dataset/lstm_4class/` ya no existe en este repo, así que las rutas que
  antes apuntaban ahí no tienen valor por defecto. Fog y Cloud fallan al
  arrancar con `RuntimeError: Faltan variables de entorno requeridas: ...`
  si no están seteadas:
  - `FEATURE_STATS_PATH` (Fog) — ruta al `.npz` con mean/std de las 192
    features del checkpoint desplegado (`dataset/lstm_6class/feature_stats.npz`).
  - `FEATURE_PREPROCESSING_PROFILE` (Fog) — nombre de la versión de modelo
    cuyo recorte (±kσ) y ablación se aplican tras estandarizar: `lstm_6class`
    para el checkpoint vigente. Se define en
    `fog/infrastructure/features/preprocessing_profiles.json` o en el archivo
    que indique `FEATURE_PREPROCESSING_PROFILES_PATH` (opcional); debe
    corresponder al `.npz` de `FEATURE_STATS_PATH`.
  - `MODEL_RUN_DIR` (Cloud) — directorio de la corrida del LSTM desplegado
    (`dataset/lstm_6class/checkpoints/<run_id>/`), con `run_config.json` y
    `best_model.pt` adentro. El `run_id` vigente puede cambiar tras un
    diagnóstico en curso — ver docs_claude/contexto_sabre.md sección 8.

  Fijar las tres con la ubicación vigente del modelo antes de arrancar, p.ej.:
  ```bash
  export FEATURE_STATS_PATH=/ruta/a/dataset/lstm_6class/feature_stats.npz
  export FEATURE_PREPROCESSING_PROFILE=lstm_6class
  export MODEL_RUN_DIR=/ruta/a/dataset/lstm_6class/checkpoints/20260928_141021
  ```

## 2. Instalación

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# torch (+ torchvision si vas a usar Fog) primero, siguiendo
# https://pytorch.org/get-started/locally/ según tu plataforma
# (CPU/CUDA/MPS) — no incluidos en requirements.txt porque el wheel
# correcto depende del hardware. -c constraints.txt fija las versiones
# verificadas juntas (torch==2.12.1, torchvision==0.27.1,
# ultralytics==8.4.75 — DEF-19, ver constraints.txt) si tu plataforma
# resuelve esos wheels; si no, instalá los que correspondan a tu hardware
# y ajustá constraints.txt.
pip install torch torchvision -c constraints.txt

pip install -r requirements.txt -c constraints.txt
```

`ultralytics` no tiene versión pinneada en `requirements.txt` (para no
acoplar el requirements.txt de desarrollo a una plataforma), pero
`constraints.txt` fija la versión verificada junto con torch/torchvision
en este entorno (`python -c "from torchvision.ops import nms; import
ultralytics"` sin error). Si ya tenés una versión fijada para
`dataset/05_extract_features.py`, usar esa misma para evitar
divergencias de comportamiento entre tracking de entrenamiento y
producción, y actualizar `constraints.txt` en consecuencia.

### Si `pip install -r requirements.txt` intenta compilar algo desde un `.tar.gz`

Normalmente significa que PyPI no tiene wheel precompilado para tu
combinación de Python + SO (frecuente con versiones de Python muy nuevas) y
pip cae a compilar desde código fuente, lo cual falla sin un toolchain de
C/Fortran/meson instalado. Alcanza con: (a) actualizar pip
(`python -m pip install --upgrade pip`), o (b) usar una versión de Python
algo más madura (3.12/3.13) con más wheels publicados. Ver el comentario
sobre `numpy==2.3.4` en `requirements.txt` para un caso concreto ya resuelto.

## 3. Variables de entorno (ver `shared/config.py`; las obligatorias se marcan)

| variable                | default                                         | uso |
|-------------------------|-------------------------------------------------|-----|
| `REDIS_URL`             | `redis://localhost:6379/0`                      | conexión Fog y Cloud |
| `YOLO_POSE_MODEL_PATH`  | `dataset/yolov8x-pose.pt`                       | modelo de pose (Fog) |
| `MODEL_RUN_DIR`         | — (obligatoria, DEF-15)                         | directorio `checkpoints/<run_id>/` del LSTM desplegado (Cloud) |
| `FEATURE_STATS_PATH`    | — (obligatoria, DEF-15)                         | mean/std de estandarización (Fog) |
| `FEATURE_PREPROCESSING_PROFILE` | — (obligatoria)                         | perfil de recorte/ablación por versión de modelo (Fog) |
| `FEATURE_PREPROCESSING_PROFILES_PATH` | JSON junto a `preprocessing_profile.py` | archivo de perfiles alternativo (Fog) |
| `DATABASE_URL`          | — (sin default; las rutas con persistencia la exigen) | PostgreSQL 16, `postgresql+asyncpg://usuario:clave@host:puerto/base` (Fog); con el compose, puerto `POSTGRES_HOST_PORT` (5433) |
| `POSTGRES_HOST_PORT`    | `5433`                                          | puerto del host donde `fog/docker-compose.yml` publica PostgreSQL (solo loopback) |
| `STORAGE_DIR`           | — (sin default; la carga de clip lo exige)      | raíz del almacenamiento local: `clips/<sha[:2]>/<sha>.<ext>` y `keypoints/<sha[:2]>/<sha>.npz`, nombrados por SHA-256 (Fog); en Docker, `/data/storage`. Disposición completa en `CONTRATO_API.md` 8.1 |
| `EVIDENCE_DIR`          | — (obligatoria al arrancar Fog)                 | log de evidencia (L01): una línea JSON por revisión cerrada en `EVIDENCE_DIR/<evento_id>.jsonl` (logger `sabre.evidencia`) y exportación L02 en `EVIDENCE_DIR/<evento_id>/`; en Docker, `/data/evidencia` |
| `M01_EXPERIMENT_LOG`    | — (opcional)                                    | `dataset/lstm_6class/EXPERIMENT_LOG.md`: de ahí el resumen de validación (L02) copia la tabla resumen de M01; sin él, indica "no disponible" |
| `CLIP_MAX_MB`           | `200`                                           | tamaño máximo del clip en `POST /matches/{id}/clip`; más de eso responde 413 (Fog) |
| `CLIP_UPLOAD_VERDICT_TIMEOUT_S` | `30.0`                                  | espera del veredicto de Cloud en la carga de clip; vencida, responde `timed_out=true` y `motivo="timeout"` (Fog) |
| `SESSION_TTL_S`         | `120.0`                                         | segundos que Fog conserva una sesión tras entregar el resultado (Fog) |
| `SESSION_SWEEP_INTERVAL_S` | `30.0`                                       | cadencia del barrido que libera sesiones vencidas (Fog) |
| `VERDICT_STREAM_TTL_S`  | `3600`                                          | `EXPIRE` del stream `cloud:verdicts:{revision_id}` (Cloud) |
| `CLAIM_MIN_IDLE_S`      | `60.0`                                          | tiempo pendiente mínimo antes de que Cloud reclame con `XAUTOCLAIM` al arrancar (Cloud) |
| `TEST_DATABASE_URL`     | — (solo pruebas)                                | base de pruebas para `pytest`; ver sección 5 |
| `LOG_LEVEL`             | `INFO`                                          | nivel del log técnico (Fog y Cloud); `aioice`, `aiortc`, `uvicorn.access` y `ultralytics` quedan siempre en WARNING |
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
`fog/infrastructure/api/schemas.py`). El WebSocket (`/ws/veredicto/{revision_id}`)
no aparece ahí porque OpenAPI no documenta WebSockets — el contrato de sus
mensajes está en `CONTRATO_API.md` sección 7.

Cloud no expone HTTP; es un loop de consumo de Redis (`python -m cloud.main`)
sin servidor.

Edge (captura RTSP de los iPhones → WebSocket para el front) es un tercer
servicio independiente, solo necesario si estás probando con video real de
las cámaras — Fog/Cloud no dependen de él. Ver sección 6.4.

### 4.1 Exportar la evidencia de una validación (L02)

Con PostgreSQL arriba y las variables `DATABASE_URL` y `EVIDENCE_DIR` fijadas (y, si quieres la
tabla de M01, `M01_EXPERIMENT_LOG`):

```bash
cd backend && source .venv/bin/activate
export M01_EXPERIMENT_LOG=../dataset/lstm_6class/EXPERIMENT_LOG.md
python scripts/exportar_evidencia.py --evento <evento_id>
```

Genera en `EVIDENCE_DIR/<evento_id>/`: `resumen.json`, `revisiones.csv` (los 16 campos de L01,
armados desde la base) y `resumen.md` (métricas por V1 y V2, umbrales, conciliación con
`EVIDENCE_DIR/<evento_id>.jsonl` e integridad de la auditoría). Todo se calcula desde
PostgreSQL; el JSONL solo se concilia y no se modifica. Es idempotente: al reejecutarlo se
sobrescriben los tres archivos y con los mismos datos solo cambia `generado_en`. El mismo
contenido de `resumen.json` está en `GET /validaciones/{evento_id}/resumen`. Sale con código 1
si falta configuración o el evento no existe.

### 4.2 Prueba de humo con una base separada

Recorre un clip por clase de `dataset/dataset trimmed/test_trimmed` hasta el veredicto. **Usa
una base, un Redis y directorios distintos a los de la validación**: cada corrida agrega
revisiones auditables que no se pueden borrar (append-only). Ejemplo con contenedores propios:

```bash
docker run -d --name sabre-humo-pg -e POSTGRES_USER=sabre -e POSTGRES_PASSWORD=humo_local \
    -e POSTGRES_DB=sabre_humo -p 127.0.0.1:5434:5432 postgres:16-alpine
redis-server --port 6390 --save "" --appendonly no --daemonize yes

cd backend && source .venv/bin/activate
export DATABASE_URL=postgresql+asyncpg://sabre:humo_local@localhost:5434/sabre_humo
export REDIS_URL=redis://localhost:6390/0
export STORAGE_DIR=/tmp/humo/storage EVIDENCE_DIR=/tmp/humo/evidencia
DS=$(cd ../dataset && pwd)                                   # rutas absolutas al dataset
export FEATURE_STATS_PATH=$DS/lstm_6class/feature_stats.npz
export FEATURE_PREPROCESSING_PROFILE=lstm_6class
export MODEL_RUN_DIR=$DS/lstm_6class/checkpoints/20260928_141021
export M01_EXPERIMENT_LOG=$DS/lstm_6class/EXPERIMENT_LOG.md
mkdir -p $STORAGE_DIR $EVIDENCE_DIR

alembic upgrade head
python scripts/registrar_modelo.py 20260928_141021
python scripts/crear_sesion_validacion.py --evento "Humo" --fecha 2026-09-29 \
    --arbitro "Arbitro Humo" --operador "Operador Humo"      # imprime evento_id y arbitro_id
python -m cloud.main &
python -m uvicorn fog.main:app --port 8001 &                 # esperar ~20 s (carga de YOLO)

python scripts/prueba_humo.py --evento <evento_id> --arbitro <arbitro_id> \
    --redis-url $REDIS_URL --salida humo.json
python scripts/exportar_evidencia.py --evento <evento_id>
```

El script sale con código 1 si algún veredicto no se registra. Las convenciones (luces del CSV,
`t_tocado_ms` = primer frame de luz / fps, brazo armado de Label Studio, veredicto con la clase
real del clip) están en su docstring. Resultados de la última corrida:
`docs/evidencia/prueba_humo_Q02.md`.

## 5. Tests

```bash
cd backend && source .venv/bin/activate
pytest tests/ -q
ruff check fog cloud shared edge --select E,F,W
```

`pytest` excluye las pruebas `slow` (ver el final de esta guía). Con Docker disponible, las
pruebas de PostgreSQL (migración, repositorios, flujo auditable, resumen) levantan un
contenedor `postgres:16-alpine` por módulo con testcontainers (254 pruebas pasan); sin Docker
ni `TEST_DATABASE_URL` se omiten (~100 pruebas omitidas). Con Colima hay que exportar
`TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`.

**`TEST_DATABASE_URL` sirve para ejecutar un solo módulo de pruebas a la vez.** Es una única
base compartida por todos los módulos y algunas pruebas exigen base vacía y cadena de
auditoría propia (`test_migracion_esquema`, `test_flujo_auditable`,
`test_search_path_funciones`): con `pytest tests/` completo contra esa base fallan 7
pruebas por interferencia entre módulos, no por el código. Usar una base vacía por módulo
(`pytest tests/fog/test_flujo_auditable.py`, recreando la base entre ejecuciones) o testcontainers.

La prueba de κ contra `sklearn` (`tests/fog/test_resumen_validacion.py`) se omite si
`scikit-learn` no está instalado; no está en `requirements.txt`.

`ruff` con las reglas `E,F,W` reporta hoy 139 hallazgos previos, casi todos `E501` (línea larga
sobre el límite por defecto de 88 caracteres); no hay configuración de `ruff` en el repo.

`tests/smoke_manual.py` es una herramienta manual para el flujo WebRTC contra Fog+Cloud+Redis
ya levantados; no es parte de la suite (su nombre evita los patrones `test_*.py` para que
`pytest` no lo recolecte, DEF-17). Requiere `pip install websockets`:

```bash
python tests/smoke_manual.py ../dataset/test/RiposteB/RiposteB_0018.mp4 \
    --fog-url http://localhost:8001 --luz-b
```

El flujo vigente de la Validación 1 (carga de clip, sin WebRTC) se prueba de punta a punta
con `scripts/prueba_humo.py` (sección 4.2).

## 6. Docker

Cada módulo (`fog/`, `cloud/`, `edge/`) tiene su propio `Dockerfile` y su
propio `docker-compose.yml`, independientes entre sí — no hay un
`docker-compose.yml` único en la raíz de `backend/`. Fog y Cloud casi no
comparten dependencias (Cloud es un worker puro: Redis + torch, sin
FastAPI/aiortc/opencv/ultralytics — ver `requirements-cloud.txt` vs
`requirements-fog.txt`), pero ambos sí dependen de `shared/` (config,
feature extractor, clasificador LSTM), que vive en la raíz de `backend/`
— por eso, aunque el `Dockerfile` de cada uno vive dentro de su propio
directorio (igual que `edge/Dockerfile`), el **build context sigue siendo
`backend/`** (ver el `context: ..` en `fog/docker-compose.yml` y
`cloud/docker-compose.yml`), no el directorio del módulo. `edge/` es la
excepción: no depende de `shared/`, así que su `docker-compose.yml` sí
buildea con contexto propio (`build: .`).

Ningún módulo tiene ya un `.env.example` — las variables que necesita cada
uno están documentadas en la sección 3 (Fog/Cloud) y en la 6.4 (Edge); se
crea el `.env` de cada módulo a mano con esos valores.

### 6.1 Fog, local

```bash
cd backend/fog
cat > .env <<'EOF'
REDIS_URL=rediss://default:PASSWORD@HOST.upstash.io:PORT
EOF
docker compose build fog
docker compose up fog
```

**Base PostgreSQL.** `fog/docker-compose.yml` también levanta `postgres`
(`postgres:16-alpine`, volumen `sabre_pgdata`; los clips y keypoints van en el
volumen `sabre_storage`). Agregar a `fog/.env`:

```bash
POSTGRES_PASSWORD=<clave>
POSTGRES_HOST_PORT=5433        # opcional; puerto del host, 5433 por defecto
DATABASE_URL=postgresql+asyncpg://sabre:<POSTGRES_PASSWORD>@localhost:<POSTGRES_HOST_PORT>/sabre
```

`POSTGRES_HOST_PORT` es el puerto del host donde se publica PostgreSQL (solo en
loopback, `127.0.0.1`); por defecto **5433**, para no chocar con un PostgreSQL
local (p. ej. el de Homebrew) que ocupe el 5432. Si lo cambias, usa el mismo
puerto en `DATABASE_URL`. Dentro de la red de Docker el contenedor sigue
escuchando en el 5432.

Levantar solo la base (sin Fog) y aplicar el esquema:

```bash
cd backend
docker compose -f fog/docker-compose.yml up -d postgres
set -a; source fog/.env; set +a        # exporta DATABASE_URL (y las demás)
alembic upgrade head
```

El esquema `sabre` lo crea Alembic (migraciones `0001` a `0003`; la `0001`
ejecuta `docs_claude/sabre_ai_schema.sql` tal cual). Si Fog corre en Docker,
también sirve `docker compose exec fog alembic upgrade head`.

Con la base migrada hay que registrar el modelo activo y crear la sesión de
validación (evento piloto, árbitro y operador; idempotente por nombre; imprime
los ids que usa la pantalla de configuración):

```bash
python scripts/registrar_modelo.py 20260928_141021
python scripts/crear_sesion_validacion.py --evento "<nombre>" --fecha YYYY-MM-DD \
    --arbitro "<nombre>" --operador "<nombre>"
```

Las pruebas de la migración usan `TEST_DATABASE_URL` (base vacía, p. ej. el
servicio de CI) o un contenedor de testcontainers. Con Colima hace falta
`TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`.

Requiere `dataset/` como sibling de `backend/` en tu filesystem (mismo
layout que la sección 1) — se monta como volumen de solo lectura
(`../../dataset` desde `fog/docker-compose.yml`, dos niveles arriba para
llegar al sibling de `backend/`), no se hornea en la imagen.

**Mac: WebRTC en Docker.** aiortc elige sus puertos UDP de ICE al azar (no
se pueden fijar a un rango — confirmado por el maintainer de aiortc en
[aiortc/aiortc#487](https://github.com/aiortc/aiortc/issues/487)), así que
el contenedor de Fog necesita `network_mode: host` (ya seteado en
`fog/docker-compose.yml`) para que esos puertos sean alcanzables. Docker
Desktop para Mac no soporta red de host de forma estable: hay un toggle
beta desde la versión 4.34 (Settings > Resources > Network > **Enable host
networking**; requiere haber iniciado sesión, desactivar *Enhanced
Container Isolation*, y reiniciar Docker Desktop) pero la comunidad reporta
inestabilidad. Si falla la conexión WebRTC con esto activado, el fallback
es correr Fog con venv (sección 2) en vez de Docker — el endpoint de subir
clip (`/matches/{match_id}/clip`) no usa WebRTC y funciona en Docker en Mac
sin esto.

### 6.2 Cloud, Render

Antes de desplegar, confirmar que el run del checkpoint vigente está
comiteado y pusheado (`run_id` — ver docs_claude/contexto_sabre.md sección 8):

```bash
git status backend/dataset/lstm_6class/checkpoints/20260928_141021/
```

Render solo ve lo que está en el repo de GitHub, no tu filesystem local —
a diferencia de `dataset/yolov8x-pose.pt` (133 MB, de Fog), este run (unos
cientos de KB) sí está pensado para vivir en el repo de `backend/`.

En Render: **New > Background Worker** (no *Web Service* — Cloud no expone
HTTP, y un Web Service espera que algún puerto responda al health check).
Conectar el repo de GitHub y configurar:

- **Dockerfile Path**: `cloud/Dockerfile` (cambió de `Dockerfile.cloud` —
  si el servicio de Render ya estaba configurado con la ruta vieja desde
  antes de este reordenamiento, **hay que actualizarlo a mano en el
  dashboard de Render**, esto no se propaga solo)
- **Root Directory**: vacío — el build sigue necesitando la raíz de
  `backend/` como contexto (`cloud/Dockerfile` hace `COPY shared/ shared/`
  y `COPY dataset/lstm_6class/checkpoints/${RUN_ID}/...`, ambos fuera de
  `cloud/`), no cambia aunque el Dockerfile ahora viva dentro de `cloud/`
- **Docker Build Args**: `RUN_ID=<run_id vigente>` si es distinto del
  default fijado en `cloud/Dockerfile` (`ARG RUN_ID=...`) — el checkpoint
  activo puede cambiar tras un diagnóstico en curso, sin tocar el Dockerfile
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

`fog/docker-compose.yml` y `cloud/docker-compose.yml` incluyen además,
cada uno, un servicio `redis` propio bajo el perfil `localdev`
(`docker compose --profile localdev up`) — solo para probar ese módulo de
forma aislada contra un Redis local sin depender de Upstash mientras
desarrollás; no reemplaza el `REDIS_URL` compartido de arriba para correr
Fog y Cloud juntos.

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

**`mediamtx` no se levanta desde `backend/`.** Ya está definido en
`SaberAISoftware/docker-compose.yml` (sibling de `backend/` — mismo nivel
que `dataset/`, ver sección 1), contenedor `sabre_mediamtx`, mismo profile
`local`, mismos puertos 1935/8554 — es una única instancia compartida por
todo el sistema (front y Edge le apuntan a la misma), no una por repo.

Antes de levantar Edge, **desde cualquier lado**, confirmar si ya está
arriba:

```bash
docker ps --filter name=sabre_mediamtx
```

Si el comando anterior no devuelve ninguna fila (no si ya aparece
`sabre_mediamtx` corriendo, como es lo normal si el front ya lo levantó
antes), recién ahí hace falta levantarlo — desde `SaberAISoftware/`, **no**
desde `backend/` ni `backend/edge/` (ese repo tiene su propio
`docker-compose.yml`, distinto al de `backend/`):

```bash
cd ../SaberAISoftware   # sibling de backend/, no backend/edge/
docker compose --profile local up -d mediamtx
```

```bash
cd backend/edge
cat > .env <<'EOF'
RTSP_FRONT_URL=rtsp://host.docker.internal:8554/live/front
RTSP_TOP_URL=rtsp://host.docker.internal:8554/live/top
WS_PORT=8002
JPEG_QUALITY=70
TARGET_FPS=15
EOF
```

| variable          | default arriba                                       | requerida | uso |
|--------------------|-----------------------------------------------------|-----------|-----|
| `RTSP_FRONT_URL`   | `rtsp://host.docker.internal:8554/live/front`        | sí        | URL RTSP de la cámara "front" servida por mediamtx |
| `RTSP_TOP_URL`     | `rtsp://host.docker.internal:8554/live/top`          | sí        | URL RTSP de la cámara "top" |
| `WS_PORT`          | `8002`                                               | no        | puerto del servidor WebSocket |
| `JPEG_QUALITY`     | `70`                                                 | no        | calidad de codificación JPEG (0-100) |
| `TARGET_FPS`       | `15`                                                 | no        | framerate de redistribución hacia los clientes WS |

Sin `RTSP_FRONT_URL`/`RTSP_TOP_URL` el proceso falla al arrancar con
`KeyError` — comportamiento esperado (falla rápido en vez de arrancar mal
configurado).

Levantar, con `mediamtx` ya arriba (paso anterior) — `edge/docker-compose.yml`
es propio del módulo, no hace falta `--profile` ni correr desde `backend/`:

```bash
cd backend/edge
docker compose up -d edge
docker compose logs -f edge   # opcional, ver los logs sin bloquear la terminal
```

Verificar:

- **edge** sirviendo WebSocket: conectarse a `ws://localhost:8002/front` o
  `ws://localhost:8002/top` (también se aceptan `/ws/camera/front` y
  `/ws/camera/top`; un mensaje binario JPEG por frame). Un GET
  HTTP plano a `http://localhost:8002/` responde `426 Upgrade Required`
  — es el comportamiento esperado del healthcheck del compose, no un error
  (`docker ps` debería mostrar el contenedor como `healthy`).
- **Reconexión:** si se corta la señal de un iPhone después de haber
  transmitido, los logs de `edge` muestran `Stream perdido, reconectando
  en Xs...` (backoff 1s→2s→4s→8s) y `Stream restaurado` al recuperarse —
  no hace falta reiniciar el contenedor.

**`Sin stream todavía (¿nadie publicó a .../live/front?)` en loop no es un
error** — es el estado normal mientras ningún iPhone esté transmitiendo
todavía a ese path (`edge` sigue reintentando con backoff hasta que
alguien publique; en los logs de `mediamtx` esto se ve como `no stream is
available on path 'live/front'`). Solo es un problema real si persiste
**después** de que Larix confirme que está transmitiendo.

**Probar el pipeline sin los iPhones**, publicando un patrón de prueba con
`ffmpeg` desde la misma máquina que corre `mediamtx` (confirma
mediamtx + edge de punta a punta antes de depender del hardware):

```bash
ffmpeg -re -f lavfi -i testsrc=size=320x240:rate=10 \
  -c:v libx264 -g 10 -pix_fmt yuv420p -f flv rtmp://localhost:1935/live/front
```

`mediamtx` tarda unos segundos desde que abre la conexión RTMP hasta que
loggea `stream is available and online` (necesita ver el primer
keyframe) — no implica ningún problema, solo hay que esperarlo antes de
que `edge` loggee `Stream restaurado` y un cliente WS empiece a recibir
frames.

## 7. Limitaciones conocidas de esta entrega

- Sin CI configurado (decisión explícita: las pruebas corren manualmente).
- `InMemoryMatchRepository` solo guarda las sesiones de procesamiento de Fog (se pierden al
  reiniciar); lo que se audita (combates, clips, clasificaciones, veredictos) está en PostgreSQL.
- Sin integración física con la luz Favero real: la Validación 1 la simula con `has_luz_A/B` y
  `t_tocado_ms` en la carga del clip (Validación 2 usa el aparato real).
- Cloud no calienta el modelo al arrancar: la primera inferencia tras iniciarlo tomó 950 ms
  (frente a 10–34 ms en caliente; presupuesto F-027 ≤ 50 ms), ver `docs/evidencia/prueba_humo_Q02.md`.
- `latencia_inferencia_ms` de Cloud no se persiste en la base.
- Edge no tiene tests automatizados ni conexión con Fog/Cloud (solo redistribuye video crudo al
  front); su healthcheck de Docker verifica que el servidor WebSocket responda, no que las cámaras
  RTSP estén conectadas — para eso hay que mirar los logs (ver sección 6.4).

## Pruebas lentas (paridad entrenamiento ↔ Fog)

`pytest tests/ -q` excluye las pruebas marcadas `slow`. La paridad de features
(`tests/fog/test_feature_parity_training_vs_fog.py`) usa YOLO real y 3 clips de
`dataset/dataset trimmed/test_trimmed`:

```bash
pytest tests/fog/test_feature_parity_training_vs_fog.py -m slow -q
```
