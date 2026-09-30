# Guía de instalación de SABRE.AI

Destinatario: la persona que instala y pone en marcha el sistema. Versión cubierta: Validación 1 (carga de clip y tocado simulado). El uso de la interfaz está en `MANUAL_USUARIO.md`.

Convenciones: los comandos son para una terminal de macOS o Linux. `<raíz>` es la carpeta que contiene los repositorios. Los pasos marcados como "No verificado en esta versión" no se ejecutaron durante la validación de esta guía.

Validación de esta guía: se siguió en un clon limpio, con una base nueva, almacenamiento y evidencia temporales, sobre macOS (arm64) con Python 3.14.5, Node v22.22.0, Docker con Colima y Redis 8.8.0.

## 1. Arquitectura desplegada

![Arquitectura desplegada](img/arquitectura_despliegue.png)

| Componente | Función | Dónde corre | Puerto |
|---|---|---|---|
| Frontend (`SaberAISoftware`) | Interfaz web de árbitro y operador | Local | 8081 |
| Fog (`backend/fog`) | API, pose, features, carga de clip, persistencia | Local (venv o Docker) | 8001 |
| Cloud (`backend/cloud`) | Worker que clasifica con el modelo y publica la sugerencia | Local, o Render como Background Worker | Sin puerto |
| Redis | Cola entre Fog y Cloud | Local, o Upstash si Cloud corre en Render | 6379 |
| PostgreSQL 16 | Registro auditable, esquema `sabre` | Local, en Docker | 5433 |
| Almacenamiento (`STORAGE_DIR`) | Clips y keypoints por SHA-256 | Local, disco de Fog | No aplica |
| Evidencia (`EVIDENCE_DIR`) | Log de evidencia y exportaciones | Local, disco de Fog | No aplica |
| Edge (`backend/edge`) | Retransmite video de cámaras (solo V2) | Local, en Docker | 8002 |
| MediaMTX | Recibe el video de las cámaras (solo V2) | Local, en Docker | 1935 y 8554 |

En la Validación 1 se instalan Frontend, Fog, Cloud, Redis y PostgreSQL. Edge y MediaMTX no se usan.

## 2. Requisitos

### Software

| Elemento | Versión | Origen |
|---|---|---|
| Python | 3.10 o superior. Verificado con 3.14.5. Las imágenes Docker usan 3.12. | `GUIA_EJECUCION.md`, `fog/Dockerfile` |
| torch | 2.12.1 | `constraints.txt` |
| torchvision | 0.27.1 | `constraints.txt` |
| ultralytics | 8.4.75 | `constraints.txt` |
| fastapi, uvicorn, pydantic | 0.138.0, 0.49.0, 2.13.4 | `requirements.txt` |
| numpy, opencv-python | 2.3.4, 4.13.0.92 | `requirements.txt` |
| redis (cliente), dependency-injector | 8.0.0, 4.49.1 | `requirements.txt` |
| sqlalchemy, asyncpg, alembic | 2.1.1, 0.31.0, 1.20.0 | `requirements.txt` |
| aiortc, av | 1.14.0, 16.1.0 | `requirements.txt` |
| Docker | Necesario para PostgreSQL | `fog/docker-compose.yml` |
| PostgreSQL | 16 (imagen `postgres:16-alpine`) | `fog/docker-compose.yml` |
| Redis (servidor) | Imagen `redis:7-alpine` en el compose. Verificado con el servidor local 8.8.0. | `fog/docker-compose.yml` |
| Node.js | Imagen `node:20-alpine` en el Dockerfile del frontend. Verificado con v22.22.0. | `SaberAISoftware/Dockerfile` |
| expo, react, react-native | ^56.0.11, 19.2.3, 0.85.3 | `SaberAISoftware/package.json` |
| Navegador | Google Chrome (usado en la validación) | |

`torch` y `torchvision` no están en `requirements.txt` porque el wheel correcto depende de la plataforma. Se instalan aparte (sección 5).

### Hardware

El repositorio no documenta requisitos de CPU, RAM ni disco. La imagen de Cloud usa torch solo para CPU. Las dos cámaras y el aparato Favero (Validación 2) exigen video H.264 de 720p o más a 30 fps o más por cámara y conexión serie RJ11 (RNF-13).

| Necesidad | Validación 1 | Validación 2 (se agrega) |
|---|---|---|
| Equipo con Docker | Sí | Sí |
| Cámaras USB (frontal y cenital) | No | Sí |
| Aparato Favero por RJ11 | No | Sí |
| Edge y MediaMTX | No | Sí |

### Archivos que no están en los repositorios

Los repositorios `backend` y `SaberAISoftware` no incluyen la carpeta `dataset/`. Debe existir como carpeta hermana de `backend/`, con:

| Ruta dentro de `dataset/` | Uso |
|---|---|
| `yolov8x-pose.pt` | Modelo de pose de Fog |
| `lstm_6class/feature_stats.npz` | Estadísticas de estandarización (`FEATURE_STATS_PATH`) |
| `lstm_6class/checkpoints/20260928_141021/` | Checkpoint desplegado: `run_config.json` y `best_model.pt` (`MODEL_RUN_DIR`) |
| `lstm_6class/results/20260928_141021_metrics.json` | Métrica que registra `registrar_modelo.py` |
| `lstm_6class/EXPERIMENT_LOG.md` | Opcional (`M01_EXPERIMENT_LOG`) |
| `dataset trimmed/test_trimmed/` y `labels/` | Solo para la prueba de humo (sección 9) |

## 3. Obtención del código

1. Cree la carpeta raíz y clone los dos repositorios. El frontend debe quedar en una carpeta llamada `SaberAISoftware`.

```bash
mkdir <raíz> && cd <raíz>
git clone https://github.com/nicolaszagal/SaberAITesis.git backend
git clone https://github.com/nicolaszagal/SaberAI-Frontend.git SaberAISoftware
```

2. Copie o enlace la carpeta `dataset/` junto a `backend/`. La disposición final es:

```text
<raíz>/backend
<raíz>/SaberAISoftware
<raíz>/dataset
```

3. Verifique que la rama sea `main` en ambos repositorios (`git branch --show-current`).

La prueba `tests/fog/test_migracion_esquema.py` además busca `docs_claude/` como carpeta hermana de `backend/`. Sin ella, esa prueba se omite.

## 4. Base de datos

1. Cree `backend/fog/.env` con la contraseña y el puerto de la base. No lo suba al repositorio.

```bash
cd <raíz>/backend
cat > fog/.env <<'EOF'
POSTGRES_PASSWORD=<clave>
POSTGRES_HOST_PORT=5433
DATABASE_URL=postgresql+asyncpg://sabre:<clave>@localhost:5433/sabre
EOF
```

2. Levante solo PostgreSQL.

```bash
docker compose -f fog/docker-compose.yml up -d postgres
```

Resultado esperado: el contenedor `postgres` queda `healthy` (`docker compose -f fog/docker-compose.yml ps`). El puerto 5433 se publica solo en `127.0.0.1`.

3. Cree el entorno de Python e instale las dependencias (sección 5), y luego aplique las migraciones.

```bash
source .venv/bin/activate
set -a; source fog/.env; set +a
alembic upgrade head
```

Resultado esperado: sin errores. La base queda en la revisión `0004` (migraciones `0001` a `0004`). Para comprobarlo:

```bash
docker compose -f fog/docker-compose.yml exec -T postgres psql -U sabre -d sabre -c "select * from alembic_version"
```

Advertencias:

- No use el PostgreSQL de Homebrew: escucha en el puerto 5432. Esta guía usa el 5433 del contenedor. Si cambia `POSTGRES_HOST_PORT`, use el mismo puerto en `DATABASE_URL`.
- Si en el mismo equipo ya existe un proyecto de Compose llamado `fog` (otra instalación), `docker compose up` lo reconfigura. Defina antes un nombre propio: `export COMPOSE_PROJECT_NAME=sabre_nueva`.

## 5. Entorno de Python y variables de entorno

### Entorno de Python

```bash
cd <raíz>/backend
python3 -m venv .venv
source .venv/bin/activate
pip install torch torchvision -c constraints.txt
pip install -r requirements.txt -c constraints.txt
```

Resultado esperado: ambos comandos terminan sin errores. Si `pip` no encuentra un wheel de `torch` para su plataforma (por ejemplo, con CUDA), instale el que indica https://pytorch.org/get-started/locally/ y ajuste `constraints.txt` a esas versiones.

### Variables de entorno

| Variable | Servicio | Obligatoria | Valor de ejemplo | Descripción |
|---|---|---|---|---|
| `DATABASE_URL` | Fog | Sí | `postgresql+asyncpg://sabre:<clave>@localhost:5433/sabre` | Base PostgreSQL. Fog no arranca sin ella. |
| `EVIDENCE_DIR` | Fog | Sí | `<raíz>/datos/evidencia` | Log de evidencia y exportaciones. Fog no arranca sin ella. |
| `FEATURE_STATS_PATH` | Fog | Sí | `<raíz>/dataset/lstm_6class/feature_stats.npz` | Estadísticas de estandarización. |
| `FEATURE_PREPROCESSING_PROFILE` | Fog | Sí | `lstm_6class` | Perfil de preprocesamiento del modelo. |
| `MODEL_RUN_DIR` | Cloud | Sí | `<raíz>/dataset/lstm_6class/checkpoints/20260928_141021` | Corrida del modelo desplegado. Cloud no arranca sin ella. |
| `STORAGE_DIR` | Fog | Sí, para cargar clips | `<raíz>/datos/storage` | Clips y keypoints por SHA-256. Sin ella la carga de clip falla. |
| `REDIS_URL` | Fog y Cloud | No | `redis://localhost:6379/0` | Conexión a Redis. Valor por defecto: el del ejemplo. |
| `POSTGRES_PASSWORD` | Compose | Sí | `<clave>` | Contraseña del contenedor de PostgreSQL. |
| `POSTGRES_HOST_PORT` | Compose | No | `5433` | Puerto del host para PostgreSQL. Por defecto 5433. |
| `YOLO_POSE_MODEL_PATH` | Fog | No | `<raíz>/dataset/yolov8x-pose.pt` | Por defecto `dataset/yolov8x-pose.pt` junto a `backend/`. |
| `FEATURE_PREPROCESSING_PROFILES_PATH` | Fog | No | | Archivo de perfiles alternativo. |
| `M01_EXPERIMENT_LOG` | Fog | No | `<raíz>/dataset/lstm_6class/EXPERIMENT_LOG.md` | Sin él, el resumen indica que la tabla de M01 no está disponible. |
| `CLIP_MAX_MB` | Fog | No | `200` | Tamaño máximo del clip. Si se supera, responde 413. |
| `CLIP_UPLOAD_VERDICT_TIMEOUT_S` | Fog | No | `30.0` | Espera de la sugerencia de Cloud al cargar un clip. |
| `FAVERO_LUZ_TIMEOUT_S` | Fog | No | `2.0` | Espera de la luz Favero antes de clasificar sin ella. |
| `SESSION_TTL_S` | Fog | No | `120.0` | Segundos que Fog conserva una sesión entregada. |
| `SESSION_SWEEP_INTERVAL_S` | Fog | No | `30.0` | Cadencia de la limpieza de sesiones. |
| `VERDICT_STREAM_TTL_S` | Cloud | No | `3600` | Vigencia del stream de sugerencia en Redis. |
| `CLAIM_MIN_IDLE_S` | Cloud | No | `60.0` | Tiempo mínimo para reclamar mensajes pendientes al arrancar. |
| `CLOUD_CONSUMER_NAME` | Cloud | No | `cloud-worker-1` | Nombre del consumidor, si hay más de una instancia. |
| `LOG_LEVEL` | Fog y Cloud | No | `INFO` | Nivel del log técnico. |
| `EXPO_PUBLIC_FOG_URL` | Frontend | No | `http://localhost:8001` | Dirección de Fog. Se fija antes de iniciar el frontend. |
| `RTSP_FRONT_URL`, `RTSP_TOP_URL` | Edge | Sí (solo V2) | `rtsp://host.docker.internal:8554/live/front` | Direcciones de las cámaras. Edge falla con `KeyError` sin ellas. |
| `WS_PORT`, `JPEG_QUALITY`, `TARGET_FPS` | Edge | No (solo V2) | `8002`, `70`, `15` | Puerto, calidad JPEG y cuadros por segundo. |
| `TEST_DATABASE_URL` | Pruebas | No | | Base de pruebas para un módulo de `pytest`. |

Si falta una variable obligatoria, Fog y Cloud terminan al arrancar con `RuntimeError: Faltan variables de entorno requeridas:` y el nombre de cada variable faltante.

Cree los directorios de trabajo en `<raíz>/datos` y exporte las variables en la terminal de cada servicio:

```bash
mkdir -p <raíz>/datos/storage <raíz>/datos/evidencia
cd <raíz>/backend && source .venv/bin/activate
set -a; source fog/.env; set +a
export STORAGE_DIR=<raíz>/datos/storage
export EVIDENCE_DIR=<raíz>/datos/evidencia
export FEATURE_STATS_PATH=<raíz>/dataset/lstm_6class/feature_stats.npz
export FEATURE_PREPROCESSING_PROFILE=lstm_6class
export MODEL_RUN_DIR=<raíz>/dataset/lstm_6class/checkpoints/20260928_141021
export M01_EXPERIMENT_LOG=<raíz>/dataset/lstm_6class/EXPERIMENT_LOG.md
```

## 6. Modelo

Registre el checkpoint desplegado en la base. El comando lo deja como versión activa.

```bash
python scripts/registrar_modelo.py 20260928_141021
```

Resultado esperado: una línea `Registrado modelo_version ... (lstm6class-20260928_141021): f1_macro_test=0.5249 activo=True`.

Sin una versión activa, la carga de clip responde 503. La verificación con `GET /modelo/activo` se hace con Fog en marcha (sección 7, paso 5).

## 7. Arranque

Use una terminal por servicio. En cada terminal de Python, ejecute antes los comandos de exportación de la sección 5.

1. Redis. Con el puerto 6379 libre:

```bash
redis-server
```

Si el 6379 está ocupado, use otro puerto y fije `REDIS_URL` en las terminales de Fog y Cloud:

```bash
redis-server --port 6391 --save "" --appendonly no --daemonize yes
export REDIS_URL=redis://localhost:6391/0
```

La opción de Redis del compose (`docker compose -f fog/docker-compose.yml --profile localdev up -d redis`): No verificado en esta versión.

2. Cloud:

```bash
cd <raíz>/backend && python -m cloud.main
```

Resultado esperado, en este orden: `Cargando <MODEL_RUN_DIR> ...`, `modelo precalentado en N ms` y `Cloud escuchando 'fog:features' como 'cloud-worker-1'...`. La línea "modelo precalentado" es la señal de que Cloud está listo. Si Cloud no puede precalentar el modelo, no arranca.

3. Fog:

```bash
cd <raíz>/backend && python -m uvicorn fog.main:app --host 0.0.0.0 --port 8001
```

Resultado esperado: `Fog listo.` y `Uvicorn running on http://0.0.0.0:8001`. En macOS pueden aparecer avisos `objc: Class AVFFrameReceiver is implemented in both`: no impidieron el funcionamiento en la validación.

4. Frontend. La primera vez, instale las dependencias:

```bash
cd <raíz>/SaberAISoftware
npm install
npx tsc --noEmit
npx expo start --web --port 8081
```

Resultado esperado: `npm install` y `tsc` terminan sin errores, y `http://localhost:8081` responde. Si Fog no corre en `http://localhost:8001`, exporte `EXPO_PUBLIC_FOG_URL` antes de `npx expo start`.

5. Verifique el modelo activo:

```bash
curl -s http://localhost:8001/modelo/activo
```

Resultado esperado: `{"nombre":"lstm6class-20260928_141021","num_clases":6,"f1_macro_test":0.5249,"kappa_piloto":null}`.

Edge y MediaMTX solo se usan en la Validación 2 (`GUIA_EJECUCION.md`, sección 6.4). No verificado en esta versión.

La ejecución de Fog en Docker (`docker compose -f fog/docker-compose.yml up fog`) exige red de host y en Mac un ajuste de Docker Desktop. No verificado en esta versión.

El despliegue de Cloud en Render (Background Worker con `cloud/Dockerfile`, argumento `RUN_ID` y `REDIS_URL` de Upstash) está descrito en `GUIA_EJECUCION.md`, secciones 6.2 y 6.3. No verificado en esta versión.

## 8. Preparar una sesión de validación

La interfaz lista los eventos y árbitros que existen en la base. Créelos con el script. Es idempotente por nombre: si ya existen, los reutiliza.

```bash
cd <raíz>/backend
python scripts/crear_sesion_validacion.py --evento "<nombre>" --fecha AAAA-MM-DD \
    --arbitro "<nombre>" --operador "<nombre>"
```

Resultado esperado: tres líneas `evento_id`, `arbitro_id` y `operador_id`, cada una con `(creado)` o `(ya existía)`. El script termina con código 1 si el evento ya existe con un tipo distinto de `piloto`. Anote el `evento_id` para la sección 10.

Para recargar la lista en la interfaz, abra "Combate" y pulse "Recargar" o recargue la página.

## 9. Verificación

### Estado del sistema

```bash
curl -s -w " %{http_code}\n" http://localhost:8001/health
```

Resultado esperado: `{"fog":"ok","redis":"ok","postgres":"ok"} 200`. Si algún componente falla, el código es 503 y ese componente dice `"error"`. En la interfaz, el encabezado muestra "Conectado".

### Prueba de humo

Recorre un clip por clase hasta el veredicto. Use una base, un Redis y directorios distintos de los de la sesión: cada corrida agrega revisiones auditables que no se pueden borrar.

1. Levante una base y un Redis separados.

```bash
docker run -d --name sabre-humo-pg -e POSTGRES_USER=sabre -e POSTGRES_PASSWORD=humo_local \
    -e POSTGRES_DB=sabre_humo -p 127.0.0.1:5434:5432 postgres:16-alpine
redis-server --port 6390 --save "" --appendonly no --daemonize yes
```

2. En una terminal nueva, exporte las variables de la prueba y prepare la base.

```bash
cd <raíz>/backend && source .venv/bin/activate
export DATABASE_URL=postgresql+asyncpg://sabre:humo_local@localhost:5434/sabre_humo
export REDIS_URL=redis://localhost:6390/0
export STORAGE_DIR=<raíz>/humo/storage EVIDENCE_DIR=<raíz>/humo/evidencia
export FEATURE_STATS_PATH=<raíz>/dataset/lstm_6class/feature_stats.npz
export FEATURE_PREPROCESSING_PROFILE=lstm_6class
export MODEL_RUN_DIR=<raíz>/dataset/lstm_6class/checkpoints/20260928_141021
export M01_EXPERIMENT_LOG=<raíz>/dataset/lstm_6class/EXPERIMENT_LOG.md
mkdir -p $STORAGE_DIR $EVIDENCE_DIR
alembic upgrade head
python scripts/registrar_modelo.py 20260928_141021
python scripts/crear_sesion_validacion.py --evento "Humo" --fecha 2026-09-29 \
    --arbitro "Arbitro Humo" --operador "Operador Humo"
```

3. En esa misma terminal, inicie un Cloud y un Fog propios de la prueba. Fog usa el puerto 8003 para no chocar con el Fog de la sesión.

```bash
python -m cloud.main &
python -m uvicorn fog.main:app --port 8003 &
```

Espere la línea `Fog listo.`

4. Ejecute la prueba con los ids que imprimió `crear_sesion_validacion.py`.

```bash
python scripts/prueba_humo.py --evento <evento_id> --arbitro <arbitro_id> \
    --fog-url http://localhost:8003 --redis-url $REDIS_URL --salida humo.json
echo $?
```

Resultado esperado: seis líneas JSON, una por clase, cada una con `"disponible": true`, `"veredicto_http": 200` y un `auditoria_seq` creciente, y código de salida 0. El script sale con código 1 si algún veredicto no se registra. Las latencias son del orden de segundos por clip (`ms_clip`).

5. Detenga los procesos de la prueba (`kill %1 %2`) y, si ya no los necesita, el contenedor (`docker stop sabre-humo-pg`) y el Redis (`redis-cli -p 6390 shutdown nosave`).

## 10. Evidencia

Fog escribe en `STORAGE_DIR` y `EVIDENCE_DIR`:

| Ruta | Contenido |
|---|---|
| `STORAGE_DIR/clips/<sha[:2]>/<sha>.<ext>` | Clip subido, nombrado por su SHA-256. |
| `STORAGE_DIR/keypoints/<sha[:2]>/<sha>.npz` | Keypoints crudos de cada clasificación. |
| `EVIDENCE_DIR/<evento_id>.jsonl` | Una línea por revisión cerrada. Solo adición. |
| `EVIDENCE_DIR/<evento_id>/` | Exportación de la sesión: `resumen.json`, `revisiones.csv`, `resumen.md`. |

Para exportar la sesión, con `DATABASE_URL` y `EVIDENCE_DIR` exportadas:

```bash
cd <raíz>/backend
python scripts/exportar_evidencia.py --evento <evento_id>
```

Resultado esperado: `Evidencia exportada en <EVIDENCE_DIR>/<evento_id>` y código 0. Los tres archivos se sobrescriben al reejecutar. El script sale con código 1 si falta configuración o el evento no existe. La evidencia no incluye nombres de atletas: usa los alias.

## 11. Respaldo y restauración

Los tres elementos se respaldan por separado. Los comandos usan el servicio `postgres` del compose.

1. Respaldo de la base:

```bash
cd <raíz>/backend
docker compose -f fog/docker-compose.yml exec -T postgres pg_dump -U sabre -d sabre > respaldo_sabre.sql
```

2. Respaldo del almacenamiento y de la evidencia:

```bash
tar -czf respaldo_archivos.tgz -C <raíz>/datos storage evidencia
```

3. Restauración de la base. Restaure siempre en una base vacía, sin ejecutar antes `alembic upgrade head`: el respaldo ya trae el esquema y la tabla `alembic_version`.

```bash
docker compose -f fog/docker-compose.yml exec -T postgres createdb -U sabre sabre_restaurada
docker compose -f fog/docker-compose.yml exec -T postgres psql -q -v ON_ERROR_STOP=1 \
    -U sabre -d sabre_restaurada < respaldo_sabre.sql
```

4. Verifique la restauración. La consulta de auditoría debe devolver 0 filas.

```bash
docker compose -f fog/docker-compose.yml exec -T postgres psql -U sabre -d sabre_restaurada \
    -c "select count(*) from sabre.veredicto" -c "select * from sabre.fn_verificar_auditoria()"
```

5. Restauración de archivos:

```bash
mkdir -p <destino> && tar -xzf respaldo_archivos.tgz -C <destino>
```

Para usar la base restaurada, cambie el nombre de la base en `DATABASE_URL`.

## 12. Solución de problemas

| Síntoma | Causa | Acción |
|---|---|---|
| Fog o Cloud terminan con `RuntimeError: Faltan variables de entorno requeridas: ...` | Falta una variable obligatoria. | Exporte las variables de la sección 5 en esa terminal. Fog exige `DATABASE_URL`, `EVIDENCE_DIR`, `FEATURE_STATS_PATH` y `FEATURE_PREPROCESSING_PROFILE`. Cloud exige `MODEL_RUN_DIR`. |
| `redis.exceptions.ConnectionError` al arrancar Cloud o Fog | Redis no está en marcha o `REDIS_URL` apunta a otro puerto. | Inicie Redis (sección 7, paso 1) y revise `REDIS_URL`. |
| La carga de un clip falla por falta de `STORAGE_DIR` | La variable no está exportada en la terminal de Fog. | Exporte `STORAGE_DIR` y reinicie Fog. |
| La carga de un clip responde 503 | No hay una versión de modelo activa. | Ejecute `scripts/registrar_modelo.py` (sección 6). |
| `alembic upgrade head` falla por conexión o autenticación | `DATABASE_URL` no apunta a la base del compose, o conecta al PostgreSQL de Homebrew (puerto 5432). | Verifique puerto y clave en `fog/.env`. Use 5433, el puerto del contenedor. |
| `docker compose up` reconfigura o reemplaza un contenedor existente | Ya existe un proyecto de Compose con el mismo nombre (`fog`). | Defina `COMPOSE_PROJECT_NAME` con otro nombre antes de ejecutar compose. |
| Puerto ocupado (6379, 8001, 8081, 5433) | Otro proceso usa el puerto. | Cambie el puerto: `POSTGRES_HOST_PORT`, `--port` de Redis o de `uvicorn`, `--port` de Expo con `EXPO_PUBLIC_FOG_URL` ajustado. Para pruebas E2E del frontend use `E2E_PORT`. |
| Un contenedor ajeno ocupa el puerto 8081 y el frontend "funciona" pero es otra versión | El servidor existente se reutiliza. | Detenga ese contenedor o use otro puerto. |
| `pip` no encuentra un wheel de `torch` o `torchvision` | La plataforma (CPU, CUDA, otro sistema) no tiene las versiones de `constraints.txt`. | Instale los wheels de https://pytorch.org/get-started/locally/ y ajuste `constraints.txt`. La imagen de Cloud usa el índice `https://download.pytorch.org/whl/cpu`. |
| `pip` intenta compilar un paquete desde un `.tar.gz` y falla | No hay wheel para su Python o sistema. | Actualice `pip` (`python -m pip install --upgrade pip`) o use un Python con más wheels publicados (3.12 o 3.13). |
| Las pruebas con `testcontainers` se omiten en Colima | `pytest` no encuentra el socket de Docker, o el contenedor Ryuk falla. | Exporte `DOCKER_HOST=unix://$HOME/.colima/default/docker.sock` y `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`. Si Ryuk falla, agregue `TESTCONTAINERS_RYUK_DISABLED=true`. El fallo de Ryuk no se reprodujo en la validación de esta guía: con esa variable las pruebas pasan. |
| La primera clasificación tarda casi 1 s más que las siguientes | El modelo no se precalentó. | Verifique que Cloud haya impreso `modelo precalentado en N ms`. Reinicie Cloud si no aparece. Antes del precalentamiento la primera inferencia tomó 950 ms (`docs/evidencia/prueba_humo_Q02.md`). |
| `/health` responde 503 | Un componente está en `"error"`. | Lea el cuerpo: `redis` indica Redis caído, `postgres` indica la base. Levante el componente. |
| La interfaz muestra "Sin conexión" | Fog no está en marcha o el frontend apunta a otra dirección. | Inicie Fog y revise `EXPO_PUBLIC_FOG_URL`. |
| La interfaz muestra "No hay eventos registrados" o "No hay árbitros registrados" | La base no tiene sesión de validación. | Ejecute `scripts/crear_sesion_validacion.py` (sección 8) y pulse "Recargar". |
| Una prueba con `testcontainers` se omite con "docs_claude/ no está junto a backend/" | Falta la carpeta hermana `docs_claude/`. | Copie `docs_claude/` junto a `backend/`. |
| Aviso `objc: Class AVFFrameReceiver is implemented in both` en macOS | `opencv-python` y `av` incluyen la misma biblioteca. | Es un aviso; no impidió el funcionamiento en la validación. |
