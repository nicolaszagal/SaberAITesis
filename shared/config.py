"""Configuración compartida entre Fog y Cloud. Todo override-able por env var.

Features de Fog: 192 por frame, idénticas a dataset/05_extract_features.py;
recorte y ablación por versión de modelo (FEATURE_PREPROCESSING_PROFILE).
Cloud despliega el pipeline de 6 clases (DEF-03 resuelto): hiperparámetros
del LSTM en `run_config.json` dentro de MODEL_RUN_DIR, no en este módulo.
"""

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# TLS mutuo hacia Redis (DEPLOY07). Rutas a archivos PEM: CA propia, certificado
# y clave de cliente. Sin ellas (modo local) el cliente no cambia. Las claves
# nunca van en el repo ni en la imagen: el entrypoint las escribe en un tmpfs.
REDIS_TLS_CA = os.environ.get("REDIS_TLS_CA") or None
REDIS_TLS_CERT = os.environ.get("REDIS_TLS_CERT") or None
REDIS_TLS_KEY = os.environ.get("REDIS_TLS_KEY") or None

# Tope aproximado (MAXLEN ~) de entradas de los streams fog:features y su
# dead-letter. Cada entrada de features pesa ~100 KB: acota la memoria de
# Redis (maxmemory 200 MB con noeviction) porque Cloud no borra lo procesado.
STREAM_MAXLEN = int(os.environ.get("STREAM_MAXLEN", "100"))

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

# Directorio del log de evidencia de la validación (logger `sabre.evidencia`):
# una línea JSON por revisión cerrada en EVIDENCE_DIR/<evento_id>.jsonl. Es
# distinto del log técnico. Sin default: Fog exige fijarlo al arrancar
# (require_paths) para no perder evidencia sin darse cuenta.
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR")

# Log de experimentos del modelo de 6 clases (dataset/lstm_6class/
# EXPERIMENT_LOG.md), del que el resumen de validación (L02) copia la tabla
# resumen de M01. Opcional y sin default: si falta, el resumen indica que la
# tabla no está disponible.
M01_EXPERIMENT_LOG = os.environ.get("M01_EXPERIMENT_LOG")

# Nivel del log técnico (INFO por defecto). Las librerías ruidosas quedan en
# WARNING aparte (ver shared/logging_config.py).
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

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
# (Redis "cloud:verdicts:{revision_id}") antes de responder con timed_out=True.
# Pipeline completo (pose+tracking+features+Redis+LSTM), no solo la espera
# corta de la luz Favero — default más generoso que FAVERO_LUZ_TIMEOUT_S.
CLIP_UPLOAD_VERDICT_TIMEOUT_S = float(os.environ.get("CLIP_UPLOAD_VERDICT_TIMEOUT_S", "30.0"))

# Presupuesto total de POST /matches/{match_id}/clip, desde que Fog recibe el
# clip hasta responder: pose+tracking+features+Cloud. Si se agota, Fog responde
# "Clasificación no disponible" con motivo `timeout` en vez de seguir analizando
# (RF-13, RNF-09, D-08: sugerencia en <= 60 s). CLIP_UPLOAD_VERDICT_TIMEOUT_S
# sigue acotando solo la espera del veredicto de Cloud dentro de este total.
CLIP_UPLOAD_TIMEOUT_S = float(os.environ.get("CLIP_UPLOAD_TIMEOUT_S", "60.0"))

# Tiempo que SessionRegistry mantiene una sesión (MatchSession) después de
# entregar el veredicto o el "no disponible", antes de liberarla (DEF-16):
# ventana para aceptar conexiones tardías de GET /ws/veredicto/{revision_id}
# que todavía no llegaron cuando el resultado quedó listo.
SESSION_TTL_S = float(os.environ.get("SESSION_TTL_S", "120.0"))

# Cada cuánto corre el barrido periódico que libera las sesiones vencidas
# (más viejas que SESSION_TTL_S desde que se cerraron). No es un requisito
# funcional, solo la cadencia del housekeeping — igual que CLAIM_MIN_IDLE_S
# más arriba.
SESSION_SWEEP_INTERVAL_S = float(os.environ.get("SESSION_SWEEP_INTERVAL_S", "30.0"))

# TTL (segundos) del stream Redis "cloud:verdicts:{revision_id}": Cloud lo fija
# con EXPIRE en cada XADD (DEF-16) para que una revisión sin consumidor no
# quede acumulando memoria en Redis indefinidamente.
VERDICT_STREAM_TTL_S = int(os.environ.get("VERDICT_STREAM_TTL_S", "3600"))

# --- Autenticación y endurecimiento de Fog (DEPLOY05) -----------------------
# Entorno de despliegue: "remoto" desactiva /docs, /redoc y /openapi.json y
# deshabilita /ws/veredicto (WebRTC no se usa en la Validación 1).
ENTORNO = os.environ.get("ENTORNO", "local")

# Usuario maestro único. El hash es Argon2id (scripts/crear_hash_password.py);
# nunca la contraseña en claro. Sin default: Fog no arranca sin ellos.
AUTH_USER = os.environ.get("AUTH_USER")
AUTH_PASSWORD_HASH = os.environ.get("AUTH_PASSWORD_HASH")

# Secreto HS256 del JWT: al menos 32 bytes aleatorios. Sin default.
AUTH_JWT_SECRET = os.environ.get("AUTH_JWT_SECRET")
AUTH_JWT_SECRET_MIN_BYTES = 32

# Una jornada de arbitraje.
AUTH_TOKEN_TTL_S = 8 * 3600

# Bloqueo por intentos: AUTH_MAX_FALLOS fallos en AUTH_VENTANA_S segundos por
# IP bloquean esa IP durante AUTH_BLOQUEO_S segundos.
AUTH_MAX_FALLOS = 5
AUTH_VENTANA_S = 15 * 60
AUTH_BLOQUEO_S = 15 * 60

# Si está definido, Fog rechaza con 403 toda petición sin `X-Proxy-Token`
# igual a este valor (el nginx del frontend lo agrega). Vacío en local.
PROXY_SHARED_TOKEN = os.environ.get("PROXY_SHARED_TOKEN") or None

# Saltos de proxy de confianza entre el cliente y Fog para `X-Forwarded-For`.
# 1: solo el proxy local o nginx (local, DEPLOY05). 2: nginx de Railway y el
# túnel de Cloudflare, que añade la IP de salida de Railway al final: el cliente
# real es la penúltima entrada (DEPLOY07).
PROXY_SALTOS_CONFIANZA = int(os.environ.get("PROXY_SALTOS_CONFIANZA", "1"))

# Orígenes CORS permitidos, separados por comas, sin comodines. Vacío en el
# despliegue remoto (mismo origen vía /api); en desarrollo http://localhost:8081.
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "")


def redis_tls_kwargs() -> dict:
    """Argumentos TLS de `redis.from_url` según `REDIS_TLS_*`.

    Returns:
        Diccionario vacío si no hay variables TLS (modo local); si no, CA,
        certificado y clave de cliente con verificación obligatoria del
        certificado del servidor y de su nombre.

    Raises:
        RuntimeError: si la configuración TLS es parcial (falta CA, certificado
            o clave).
    """
    partes = (REDIS_TLS_CA, REDIS_TLS_CERT, REDIS_TLS_KEY)
    if not any(partes):
        return {}
    if not all(partes):
        raise RuntimeError(
            "TLS de Redis incompleto: definir REDIS_TLS_CA, "
            "REDIS_TLS_CERT y REDIS_TLS_KEY."
        )
    return {
        "ssl_ca_certs": REDIS_TLS_CA,
        "ssl_certfile": REDIS_TLS_CERT,
        "ssl_keyfile": REDIS_TLS_KEY,
        "ssl_cert_reqs": "required",
        "ssl_check_hostname": True,
    }


def cors_origins() -> list[str]:
    """Lista de orígenes CORS permitidos, tomada de `CORS_ORIGINS`.

    Returns:
        Orígenes sin espacios ni vacíos; lista vacía si no hay ninguno.

    Raises:
        RuntimeError: si algún origen es el comodín `*`.
    """
    origenes = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    if "*" in origenes:
        raise RuntimeError("CORS_ORIGINS no admite comodines: listar cada origen.")
    return origenes


def require_auth() -> None:
    """Falla si la configuración de autenticación falta o es débil.

    Fog la llama al arrancar, antes de construir la app.

    Raises:
        RuntimeError: si falta `AUTH_USER`, `AUTH_PASSWORD_HASH` o
            `AUTH_JWT_SECRET`, o si el secreto tiene menos de 32 bytes.
            El mensaje nunca incluye los valores.
    """
    faltan = [
        n for n in ("AUTH_USER", "AUTH_PASSWORD_HASH", "AUTH_JWT_SECRET")
        if not globals().get(n)
    ]
    if faltan:
        raise RuntimeError(
            "Faltan variables de autenticación requeridas: " + ", ".join(faltan) + "."
        )
    if len(AUTH_JWT_SECRET.encode()) < AUTH_JWT_SECRET_MIN_BYTES:
        raise RuntimeError(
            f"AUTH_JWT_SECRET debe tener al menos {AUTH_JWT_SECRET_MIN_BYTES} bytes."
        )


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
