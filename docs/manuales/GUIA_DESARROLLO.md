# Guía de desarrollo de SABRE.AI

Para quien modifica el código o corre las pruebas. Si solo quiere instalar y usar el sistema, vea [`GUIA_INSTALACION.md`](GUIA_INSTALACION.md) y [`GUIA_EJECUCION.md`](GUIA_EJECUCION.md). El contrato de la API está en [`../../CONTRATO_API.md`](../../CONTRATO_API.md) y no se repite aquí.

Todos los comandos se corren desde `<carpeta-del-proyecto>/backend` con el entorno virtual activo:

```bash
cd <carpeta-del-proyecto>/backend
source .venv/bin/activate
```

## 1. Pruebas del backend

```bash
pytest tests/ -q
```

### 1.1 `TEST_DATABASE_URL` y las pruebas omitidas

Las pruebas que usan PostgreSQL (migraciones, repositorios, flujo auditable, resumen de validación, respaldo) necesitan una instancia de PostgreSQL 16. Hay dos formas de dársela:

1. **`TEST_DATABASE_URL` (recomendada).** Apunta a una *instancia*, no a una base que se reutilice. Cada módulo de pruebas crea su propia base vacía (`test_<módulo>_<aleatorio>`), le aplica las migraciones y la elimina al terminar (`DROP DATABASE ... WITH (FORCE)`). Por eso `pytest tests/` se puede repetir sobre la misma instancia. El usuario de la URL necesita el permiso `CREATEDB`. Con el PostgreSQL de Docker que levanta `instalar_fog.sh` (usuario `sabre`, puerto `POSTGRES_HOST_PORT`, 5436 por defecto):

   ```bash
   export TEST_DATABASE_URL="postgresql+asyncpg://sabre:$(cat .secrets/postgres_password.txt)@127.0.0.1:5436/postgres"
   pytest tests/ -q
   ```

   Use otra base de datos de esa instancia (aquí `postgres`) como puerta de entrada; no use la base `sabre` de una validación.
2. **testcontainers.** Sin `TEST_DATABASE_URL` y con Docker disponible, cada módulo levanta un contenedor `postgres:16-alpine`. Con Colima hay que exportar `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`.

**Qué significa que haya pruebas omitidas** (`skipped` en el resumen de `pytest`): sin `TEST_DATABASE_URL` y sin Docker, las pruebas que dependen de PostgreSQL se omiten en vez de fallar. Un resumen con muchas omitidas **no prueba nada de la base**: no lo tome como "todo en verde". El resumen que vale es el que no omite pruebas por falta de base.

**Dos omitidas son normales en un clon del backend solo**, y `-rs` muestra su motivo:

```text
SKIPPED [1] tests/fog/test_migracion_esquema.py:37: docs_claude/ no está junto a backend/
SKIPPED [1] tests/fog/test_resumen_validacion.py:351: dataset/ no está junto al backend
```

La primera necesita `docs_claude/` (la documentación funcional del repositorio raíz del autor, que no se distribuye) y la segunda, el conjunto de datos del autor (no está en git).

**`scikit-learn` no viene en el lock de Fog.** La prueba de κ contra `sklearn` (`tests/fog/test_resumen_validacion.py::test_kappa_coincide_con_scikit_learn`) **falla** con `ModuleNotFoundError: No module named 'sklearn'` si solo instaló el lock. Instálelo con la versión de `requirements.txt` (no se edita el lock a mano):

```bash
pip install scikit-learn==1.9.1 -c constraints.txt
```

El resultado de la corrida de DOC01 (equipo y fecha) está en la sección 7.

### 1.2 Límite de tiempo (pytest-timeout)

Cada prueba tiene un límite de 120 s (`timeout = 120` en `pytest.ini`, plugin `pytest-timeout`). Una prueba que lo excede falla con `Timeout >120.0s` y el informe muestra dónde estaba, en vez de dejar colgada la suite. Para una prueba puntual más larga, use `@pytest.mark.timeout(300)`; con `--timeout=0` se desactiva.

### 1.3 Pruebas lentas de paridad (entrenamiento ↔ Fog)

`pytest.ini` excluye las pruebas marcadas `slow` (`addopts = -m "not slow"`). La paridad de features (`tests/fog/test_feature_parity_training_vs_fog.py`) usa YOLO real y clips del conjunto de datos del autor, que **no están en el repositorio** (ver [`LIMITACIONES.md`](LIMITACIONES.md), sección 7). Sin esos clips la prueba no se puede correr:

```bash
pytest tests/fog/test_feature_parity_training_vs_fog.py -m slow -q
```

### 1.4 Estilo (ruff)

```bash
ruff check fog cloud shared --select E,F,W
```

`ruff.toml` fija `line-length = 120`. Debe terminar sin avisos.

## 2. Pruebas del frontend (Playwright)

```bash
cd <carpeta-del-proyecto>/SaberAISoftware
npm install
npx tsc --noEmit
npx playwright test
```

- `playwright.config.ts` levanta el Expo local (`expo start --web`) en el puerto **8099** y lo usa como `baseURL`. Se cambia con `E2E_PORT` (por ejemplo `E2E_PORT=8091 npx playwright test`).
- Si el puerto ya está ocupado, la corrida **falla** en vez de probar contra lo que haya escuchando. Solo con `E2E_REUSE=1` se reutiliza un Expo local ya levantado.
- `e2e/globalSetup.ts` aborta si lo servido no es el Expo local (por ejemplo, el nginx de un contenedor o un despliegue). Nunca corra las pruebas contra un despliegue.
- Las pruebas E2E usan datos de prueba propios de `e2e/fixtures/` y una API simulada; no hace falta Fog. Las capturas del manual son otra cosa: usan el sistema real (`e2e/capturas-manual.spec.ts`, ver [`MANUAL_USUARIO.md`](MANUAL_USUARIO.md)).

### 2.1 Regenerar las capturas del manual

Las capturas de [`MANUAL_USUARIO.md`](MANUAL_USUARIO.md) se toman sobre el **sistema real** (Fog, Cloud, Redis y PostgreSQL levantados, sin API simulada) con `e2e/capturas-manual.spec.ts` y su propia configuración, que usa la interfaz ya servida (por defecto la de Docker, `http://localhost:8081`). El spec oculta el video (`opacity: 0`): los clips son de competencia y sus derechos de imagen no son del autor.

```bash
cd <carpeta-del-proyecto>/SaberAISoftware
CAPTURAS=1 SISTEMA_REAL=1 SABRE_USUARIO=<usuario> SABRE_PASSWORD=<contraseña> \
CAPTURAS_DIR=<carpeta-del-proyecto>/backend/docs/manuales/img \
EVENTO_NOMBRE="<evento sin revisiones>" ARBITRO_NOMBRE="<árbitro del catálogo>" \
CLIP_1=<ruta> CLIP_2=<ruta> CLIP_SIN_TIRADORES=<ruta> CLIP_1_T_MS=<ms> CLIP_2_T_MS=<ms> \
npx playwright test -c playwright.capturas.config.ts
```

Las variables (rutas de los clips y su instante de luz) están descritas en la cabecera del spec. Necesita Google Chrome (`channel: 'chrome'`, el Chromium de Playwright no reproduce H.264) y un evento **sin revisiones**: el spec espera exactamente 3 en el historial y las revisiones no se pueden borrar. El spec termina cerrando la sesión de validación (borra los clips de esa sesión).

## 3. Arquitectura hexagonal

Fog (`fog/`) y Cloud (`cloud/`) siguen la misma estructura:

| Carpeta | Contenido | Qué puede importar |
|---|---|---|
| `domain/` | Entidades, reglas y errores. | Solo la biblioteca estándar y otros módulos de `domain/`. |
| `application/` | Casos de uso (un archivo por caso: `abrir_revision.py`, `registrar_veredicto.py`, ...). | `domain/` y los puertos de `ports/`. **Ninguna** librería de infraestructura. |
| `ports/` | Interfaces (clases abstractas) que el dominio y los casos de uso necesitan: repositorios, almacenamiento, pose, mensajería, emisión de tokens... | `domain/`. |
| `infrastructure/` | Implementaciones concretas: FastAPI (`api/`), PostgreSQL (`persistence/`), Redis (`messaging/`), YOLO (`pose/`), disco (`storage/`), JWT y Argon2 (`auth/`)... | Todo lo anterior y librerías externas. |
| `composition.py` | **Raíz de composición**: el único lugar que conoce las implementaciones concretas e instancia el grafo de dependencias (con `dependency_injector`). | Todo. |
| `main.py` | Crea el contenedor de `composition.py` y arranca la aplicación (Fog: FastAPI; Cloud: bucle de consumo de Redis). | `composition.py`. |

Reglas de trabajo:

1. Dominio y casos de uso no importan infraestructura. Una integración nueva (otra base, otro detector de pose) va detrás de un puerto en `ports/` y se ensambla en `composition.py`.
2. El código compartido entre nodos va en `shared/` (configuración en `shared/config.py`, tiempos, contratos).
3. El sistema solo **sugiere**: ningún código asigna puntos ni cierra una revisión sin la decisión del árbitro (RNF-01).
4. Los registros de revisión son de solo adición (RNF-05): no hay `UPDATE` ni `DELETE` sobre la auditoría.
5. Si agrega una variable de entorno, se define en `shared/config.py` y se documenta en [`GUIA_EJECUCION.md`](GUIA_EJECUCION.md).

El diseño completo está en [`../../PLAN_ARQUITECTURA_DDD.md`](../../PLAN_ARQUITECTURA_DDD.md).

## 4. Ramas y commits

- Rama que prevalece: `main`, en backend y frontend. Los cambios de documentación del repositorio raíz se commitean en `master`.
- Se trabaja en una rama por tarea: `feature/<ID>` (funcionalidad), `fix/<DEF-xx>` (corrección) o `docs/<ID>` (documentación), y se fusiona a `main` al terminar.
- Commits convencionales con el identificador de la tarea: `fix(DEF-08): ...`, `feat(F-033): ...`, `docs(DOC01): ...`.
- Toda corrección incluye una prueba que **falla antes y pasa después**. No se da una tarea por terminada con pruebas en rojo.
- Documentación y comentarios en español. Docstrings en estilo Google (`Args`, `Returns`, `Raises`) en las funciones públicas nuevas o modificadas.
- El código del Edge y del lector Favero no está en `main`: vive en la rama `future/edge-favero`.

## 5. Variables de entorno

Se leen en `shared/config.py` (la fuente de verdad). Con `scripts/fog_nativo.sh` y `scripts/instalar_fog.sh` casi todas las fija `scripts/lib_fog_env.sh`; no hace falta exportarlas a mano. Las obligatorias no tienen valor por defecto: sin ellas Fog o Cloud fallan al arrancar con `RuntimeError: Faltan variables de entorno requeridas: ...` (DEF-15).

| Variable | Por defecto | Uso |
|---|---|---|
| `DATABASE_URL` | — (obligatoria, Fog) | PostgreSQL 16: `postgresql+asyncpg://usuario:clave@host:puerto/base` |
| `REDIS_URL` | `redis://localhost:6379/0` | Conexión de Fog y Cloud |
| `STORAGE_DIR` | — (la carga de clip la exige) | Raíz del almacenamiento: `clips/<sha[:2]>/<sha>.<ext>` y `keypoints/<sha[:2]>/<sha>.npz` (ver `CONTRATO_API.md`, 8.1) |
| `EVIDENCE_DIR` | — (obligatoria, Fog) | Log de evidencia L01 (`<evento_id>.jsonl`) y exportación L02 |
| `FEATURE_STATS_PATH` | — (obligatoria, Fog) | `.npz` con media y desviación de las 192 features del checkpoint desplegado |
| `FEATURE_PREPROCESSING_PROFILE` | — (obligatoria, Fog) | Perfil de recorte y ablación de la versión de modelo (`lstm_6class`); está en `fog/infrastructure/features/preprocessing_profiles.json` |
| `FEATURE_PREPROCESSING_PROFILES_PATH` | el JSON anterior | Archivo de perfiles alternativo |
| `MODEL_RUN_DIR` | — (obligatoria, Cloud) | `checkpoints/<run_id>/` con `run_config.json` y `best_model.pt` |
| `YOLO_POSE_MODEL_PATH` | `dataset/yolov8x-pose.pt` | Pesos de pose (Fog) |
| `FOG_DEVICE` | `cpu` | Dispositivo de YOLO. Con otro valor `fog_nativo.sh` exige la prueba de equivalencia |
| `AUTH_USER`, `AUTH_PASSWORD_HASH`, `AUTH_JWT_SECRET` | — (obligatorias, Fog) | Usuario maestro, su hash Argon2id y el secreto del JWT |
| `ENTORNO` | `local` | `remoto` desactiva `/docs`, `/redoc` y `/openapi.json` y exige Redis con TLS |
| `CORS_ORIGINS` | vacío (`.env.example` trae `http://localhost:8081`) | Orígenes permitidos, separados por comas, sin comodines |
| `CLIP_MAX_MB` | `200` | Tamaño máximo del clip (si no, 413) |
| `CLIP_UPLOAD_TIMEOUT_S`, `CLIP_UPLOAD_VERDICT_TIMEOUT_S` | `60`, `30` | Presupuesto total de la carga de clip y espera del veredicto de Cloud |
| `VENTANA_PRE_MS`, `VENTANA_POST_MS` | `2000`, `500` | Ventana del clip alrededor del tocado (D-19) |
| `SESSION_TTL_S`, `SESSION_SWEEP_INTERVAL_S` | `120`, `30` | Vida de una sesión de procesamiento en Fog y cadencia del barrido |
| `VERDICT_STREAM_TTL_S`, `CLAIM_MIN_IDLE_S`, `CLOUD_CONSUMER_NAME` | `3600`, `60`, `cloud-worker-1` | Cloud: `EXPIRE` del stream de veredictos, reclamo de pendientes y nombre del consumidor |
| `RESPALDO_DIR` | — (la define `.env`) | Carpeta de respaldos, fuera de Docker y del repo; la lee `scripts/respaldar_sesion.sh` |
| `RESPALDO_SCRIPT`, `RESPALDO_TIMEOUT_S` | `scripts/respaldar_sesion.sh`, `600` | Script y plazo del respaldo que ejecuta el cierre de sesión |
| `LOG_LEVEL` | `INFO` | Nivel del log técnico (`uvicorn.access` y `ultralytics` quedan en WARNING) |
| `M01_EXPERIMENT_LOG` | — (opcional) | `EXPERIMENT_LOG.md` del entrenamiento: de ahí el resumen (L02) copia la tabla de M01; sin él, "no disponible" |
| `TEST_DATABASE_URL` | — (solo pruebas) | Ver la sección 1.1 |
| `REDIS_TLS_CA`, `REDIS_TLS_CERT`, `REDIS_TLS_KEY`, `PROXY_SHARED_TOKEN`, `PROXY_SALTOS_CONFIANZA`, `REDIS_SOCKET_TIMEOUT_S`, `REDIS_CONNECT_TIMEOUT_S`, `REDIS_HEALTH_CHECK_S`, `CLOUD_XREAD_BLOCK_MS`, `CLOUD_REDIS_FALLOS_MAX`, `CLOUD_REDIS_ESPERA_S`, `STREAM_MAXLEN` | — | Despliegue remoto: ver [`DESPLIEGUE_REMOTO.md`](DESPLIEGUE_REMOTO.md) |

## 6. Dependencias

- Las dependencias de Fog están **bloqueadas por plataforma**: `requirements-fog.lock` (macOS arm64) y `requirements-fog.linux-x86_64.lock` (Linux x86_64). Se instalan con `pip install -r <lock> -c constraints.txt`. `constraints.txt` fija `torch`, `torchvision` y `ultralytics`. No edite un lock a mano: si cambia una versión, se regenera y se vuelve a correr la prueba de equivalencia (`sh scripts/instalar_fog.sh probar`, que necesita los clips de referencia del autor).
- `requirements.txt` es el conjunto de desarrollo; `requirements-fog.txt` y `requirements-cloud.txt` son las de cada imagen de Docker.

## 7. Resultado de la corrida de verificación (DOC01, 20/11/2026)

En un clon limpio de `main` (entorno nuevo con `requirements-fog.lock` y `scikit-learn==1.9.1`), con `TEST_DATABASE_URL` apuntando al PostgreSQL de Docker, en un MacBook Air Apple M4 (macOS 27.0.1, Python 3.14.5):

```text
618 passed, 2 skipped, 3 deselected, 1 warning in 131.82s (0:02:11)
```

- Las 2 omitidas son las de la sección 1.1. Las deseleccionadas son las `slow` (sección 1.3): son 3 en un clon sin el conjunto de datos y 5 cuando el autor lo tiene junto al repositorio (el número depende de los clips que encuentra).
- Sin `scikit-learn` la misma corrida dio `617 passed, 1 failed, 2 skipped` (el fallo de κ).
- `ruff check fog cloud shared --select E,F,W`: `All checks passed!`.
