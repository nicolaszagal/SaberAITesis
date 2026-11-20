"""Configuración compartida entre Fog y Cloud. Todo override-able por env var.

Features de Fog: 192 por frame, idénticas a dataset/05_extract_features.py;
recorte y ablación por versión de modelo (FEATURE_PREPROCESSING_PROFILE).
Cloud despliega el pipeline de 6 clases (DEF-03 resuelto): hiperparámetros
del LSTM en `run_config.json` dentro de MODEL_RUN_DIR, no en este módulo.
"""

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# Valor crudo de REDIS_URL (None si falta): `require_redis_remoto` no acepta el valor por defecto.
REDIS_URL_ENV = os.environ.get("REDIS_URL")

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

# Dispositivo de cómputo de YOLO en Fog (DEPLOY10). `cpu` es lo que corrió en la Validación 1;
# `mps` (Apple) o `cuda`/`cuda:N` son opcionales y solo se aceptan si `scripts/instalar_fog.sh probar`
# pasa con ese dispositivo (la equivalencia de features no se da por supuesta). Nunca se deja que
# ultralytics elija solo: sin este valor explícito, un equipo con GPU CUDA cambiaría de dispositivo.
FOG_DEVICE = os.environ.get("FOG_DEVICE", "cpu").strip() or "cpu"
DISPOSITIVOS_VALIDOS = ("cpu", "mps", "cuda")


def validar_dispositivo(dispositivo: str) -> str:
    """Comprueba que `FOG_DEVICE` sea `cpu`, `mps`, `cuda` o `cuda:<N>`.

    Args:
        dispositivo: valor de `FOG_DEVICE`.

    Returns:
        El mismo valor, si es válido.

    Raises:
        RuntimeError: si el valor no es uno de los admitidos.
    """
    base, dos_puntos, indice = dispositivo.partition(":")
    if base not in DISPOSITIVOS_VALIDOS or (dos_puntos and (base != "cuda" or not indice.isdigit())):
        raise RuntimeError(
            f"FOG_DEVICE={dispositivo!r} no es válido: use cpu, mps, cuda o cuda:<N>."
        )
    return dispositivo

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
# docs/manuales/GUIA_DESARROLLO.md, sección 5).
MODEL_RUN_DIR = os.environ.get("MODEL_RUN_DIR")

# Estadísticas de estandarización (mean/std, shape (192,), calculadas solo
# sobre train) — ver dataset/lstm_4class/compute_stats.py. FeatureExtractorPort
# en Fog las usa para replicar el preprocesamiento de entrenamiento.
#
# Sin default (DEF-15): antes apuntaba a dataset/lstm_4class/feature_stats.npz,
# que ya no existe en este repo. Fog debe fijar esta variable explícitamente
# con la ubicación vigente (ver require_paths() más abajo y docs/manuales/GUIA_DESARROLLO.md, sección 5).
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
# Ventana del clip alrededor del tocado (EDGE02, cierra DEF-32; reemplaza los 5 s de RF-01):
# 2000 ms antes y 500 ms después. La usan Edge, que recorta en vivo, y Fog, que recorta los
# clips subidos a mano. Un clip que ya viene recortado no cambia (idempotente, tolerancia de
# un frame).
VENTANA_PRE_MS = int(os.environ.get("VENTANA_PRE_MS", "2000"))
VENTANA_POST_MS = int(os.environ.get("VENTANA_POST_MS", "500"))

# Respaldo verificado que corre el cierre de sesión (EDGE02): script y tiempo máximo.
RESPALDO_SCRIPT = os.environ.get("RESPALDO_SCRIPT", "scripts/respaldar_sesion.sh")
RESPALDO_TIMEOUT_S = float(os.environ.get("RESPALDO_TIMEOUT_S", "600"))

CLIP_MAX_MB = float(os.environ.get("CLIP_MAX_MB", "200"))

# Tiempo que POST /matches/{match_id}/clip espera el veredicto de Cloud
# (Redis "cloud:verdicts:{revision_id}") antes de responder con timed_out=True.
# Pipeline completo (pose+tracking+features+Redis+LSTM).
CLIP_UPLOAD_VERDICT_TIMEOUT_S = float(os.environ.get("CLIP_UPLOAD_VERDICT_TIMEOUT_S", "30.0"))

# Presupuesto total de POST /matches/{match_id}/clip, desde que Fog recibe el
# clip hasta responder: pose+tracking+features+Cloud. Si se agota, Fog responde
# "Clasificación no disponible" con motivo `timeout` en vez de seguir analizando
# (RF-13, RNF-09, D-08: sugerencia en <= 60 s). CLIP_UPLOAD_VERDICT_TIMEOUT_S
# sigue acotando solo la espera del veredicto de Cloud dentro de este total.
CLIP_UPLOAD_TIMEOUT_S = float(os.environ.get("CLIP_UPLOAD_TIMEOUT_S", "60.0"))

# Tiempo que SessionRegistry mantiene una sesión (MatchSession) después de
# entregar el veredicto o el "no disponible", antes de liberarla (DEF-16).
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
# Entorno de despliegue: "remoto" desactiva /docs, /redoc y /openapi.json.
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


# --- Cloud vivo ante la pérdida de Redis (FIX04) ---------------------------------------------------
# Tiempos del cliente Redis de Cloud. `socket_timeout` debe superar el BLOCK del XREADGROUP con margen
# (la espera bloqueante la corta Redis, no el socket). Con estos valores un corte silencioso (socket
# abierto que no contesta) hace salir a Cloud en ~17 s: 3 fallos de 5 s más 1 s de espera entre ellos.
REDIS_SOCKET_TIMEOUT_S = float(os.environ.get("REDIS_SOCKET_TIMEOUT_S", "5.0"))
REDIS_CONNECT_TIMEOUT_S = float(os.environ.get("REDIS_CONNECT_TIMEOUT_S", "3.0"))
REDIS_HEALTH_CHECK_S = int(os.environ.get("REDIS_HEALTH_CHECK_S", "3"))
CLOUD_XREAD_BLOCK_MS = int(os.environ.get("CLOUD_XREAD_BLOCK_MS", "2000"))
# Fallos de conexión seguidos tras los cuales Cloud sale con código distinto de 0.
CLOUD_REDIS_FALLOS_MAX = int(os.environ.get("CLOUD_REDIS_FALLOS_MAX", "3"))
CLOUD_REDIS_ESPERA_S = float(os.environ.get("CLOUD_REDIS_ESPERA_S", "1.0"))


def cloud_redis_kwargs() -> dict:
    """Argumentos de tiempo de `redis.from_url` para Cloud, validados.

    Returns:
        `socket_timeout`, `socket_connect_timeout` y `health_check_interval`.

    Raises:
        RuntimeError: si `REDIS_SOCKET_TIMEOUT_S` no supera en al menos 1 s el bloqueo del
            XREADGROUP (`CLOUD_XREAD_BLOCK_MS`) o si algún tiempo no es positivo.
    """
    if min(REDIS_SOCKET_TIMEOUT_S, REDIS_CONNECT_TIMEOUT_S, REDIS_HEALTH_CHECK_S,
           CLOUD_XREAD_BLOCK_MS, CLOUD_REDIS_FALLOS_MAX) <= 0:
        raise RuntimeError("Los tiempos y el máximo de fallos de Redis deben ser positivos.")
    if REDIS_SOCKET_TIMEOUT_S * 1000 < CLOUD_XREAD_BLOCK_MS + 1000:
        raise RuntimeError(
            "REDIS_SOCKET_TIMEOUT_S debe superar CLOUD_XREAD_BLOCK_MS en al menos 1 s: con el "
            "socket más corto que el bloqueo, cada lectura vacía se contaría como fallo."
        )
    return {
        "socket_timeout": REDIS_SOCKET_TIMEOUT_S,
        "socket_connect_timeout": REDIS_CONNECT_TIMEOUT_S,
        "health_check_interval": REDIS_HEALTH_CHECK_S,
    }


def require_redis_remoto() -> None:
    """Exige Redis con TLS explícito cuando `ENTORNO` es `remoto`.

    Cloud y Fog la llaman al arrancar. Sin ella, un `REDIS_URL` ausente caía en el valor por
    defecto (`redis://localhost:6379/0`, sin TLS) y el servicio se reiniciaba en bucle (DEPLOY09).
    En entorno local no exige nada.

    Raises:
        RuntimeError: si falta `REDIS_URL`, si no empieza por `rediss://` o si falta alguna
            de `REDIS_TLS_CA`, `REDIS_TLS_CERT` y `REDIS_TLS_KEY`. El mensaje nombra la
            variable y nunca incluye valores.
    """
    if ENTORNO != "remoto":
        return
    if not REDIS_URL_ENV:
        raise RuntimeError("ENTORNO=remoto exige REDIS_URL (sin valor por defecto): falta.")
    if not REDIS_URL_ENV.startswith("rediss://"):
        raise RuntimeError("ENTORNO=remoto exige que REDIS_URL empiece por rediss:// (TLS).")
    faltan = [n for n in ("REDIS_TLS_CA", "REDIS_TLS_CERT", "REDIS_TLS_KEY") if not globals().get(n)]
    if faltan:
        raise RuntimeError("ENTORNO=remoto exige " + ", ".join(faltan) + ": falta.")


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


# --- Transporte Fog -> Cloud por HTTP (DEPLOY11) ---------------------------------------------------
# `redis` (por defecto, modo A local) o `http` (modo remoto: Fog sale por HTTPS hacia Cloud y no usa Redis).
CLOUD_TRANSPORTES = ("redis", "http")
CLOUD_TRANSPORTE = (os.environ.get("CLOUD_TRANSPORTE") or "redis").strip().lower()

# Fog: dirección de Cloud y archivo con el token del nodo. Solo `https://` (o `http://localhost` en pruebas).
CLOUD_URL = (os.environ.get("CLOUD_URL") or "").strip()
CLOUD_TOKEN_FILE = os.environ.get("CLOUD_TOKEN_FILE", ".secrets/cloud_token.txt")
# Tiempo máximo de una clasificación pedida a Cloud, desde Fog. Debe quedar bajo
# CLIP_UPLOAD_VERDICT_TIMEOUT_S: si no, la espera del veredicto la corta antes (RNF-04: 60 s en total).
CLOUD_HTTP_TIMEOUT_S = float(os.environ.get("CLOUD_HTTP_TIMEOUT_S", "25.0"))

# Cloud: hashes SHA-256 de los tokens de nodo, `nombre:hash` separados por comas o saltos de línea.
# Sin esta variable Cloud no abre su API HTTP (solo consume Redis, como en el modo A).
CLOUD_NODOS_SHA256 = os.environ.get("CLOUD_NODOS_SHA256") or None
# Puerto de la API HTTP de Cloud: `PORT` es el que asigna Railway.
CLOUD_HTTP_PUERTO = int(os.environ.get("PORT") or os.environ.get("CLOUD_HTTP_PUERTO") or "8002")
CLOUD_HTTP_HOST = os.environ.get("CLOUD_HTTP_HOST", "0.0.0.0")
# Cuerpo máximo de POST /v1/clasificar. Una revisión típica pesa unas decenas de KB (T x 192 x 4 bytes,
# en base64): 2 MiB deja margen holgado y corta cargas absurdas.
CLOUD_HTTP_MAX_BODY_BYTES = int(os.environ.get("CLOUD_HTTP_MAX_BODY_BYTES", str(2 * 1024 * 1024)))
# Peticiones por token y por ventana. Una revisión VAR hace una sola petición.
CLOUD_HTTP_LIMITE_PETICIONES = int(os.environ.get("CLOUD_HTTP_LIMITE_PETICIONES", "30"))
CLOUD_HTTP_LIMITE_VENTANA_S = float(os.environ.get("CLOUD_HTTP_LIMITE_VENTANA_S", "60"))
# Tiempo máximo de una petición en Cloud (cola de inferencia incluida). Menor que el de Fog.
CLOUD_HTTP_PETICION_TIMEOUT_S = float(os.environ.get("CLOUD_HTTP_PETICION_TIMEOUT_S", "20.0"))


def redis_activo() -> bool:
    """Indica si Cloud debe consumir Redis: solo si hay `REDIS_URL` en el entorno.

    Returns:
        True si `REDIS_URL` está definido y no vacío.
    """
    return bool(REDIS_URL_ENV)


def validar_cloud_url(url: str) -> str:
    """Comprueba que `CLOUD_URL` sea `https://` (o `http://localhost`/`127.0.0.1` en pruebas).

    Args:
        url: valor de `CLOUD_URL`.

    Returns:
        La URL sin barra final.

    Raises:
        RuntimeError: si falta, no es una URL con host o usa `http://` hacia un host remoto.
            El mensaje nunca incluye la URL completa (podría llevar credenciales).
    """
    from urllib.parse import urlsplit

    if not url:
        raise RuntimeError("CLOUD_TRANSPORTE=http exige CLOUD_URL: falta.")
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise RuntimeError("CLOUD_URL no es una URL válida (https://host[:puerto]).")
    if partes.username or partes.password:
        raise RuntimeError("CLOUD_URL no admite usuario ni clave: el token va en su archivo.")
    if partes.scheme == "http" and partes.hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError(
            "CLOUD_URL debe empezar por https:// (http:// solo se admite hacia localhost, en pruebas)."
        )
    return url.rstrip("/")


def validar_transporte_cloud(transporte: str) -> str:
    """Comprueba el valor de `CLOUD_TRANSPORTE`.

    Args:
        transporte: `redis` o `http`.

    Returns:
        El mismo valor.

    Raises:
        RuntimeError: si no es uno de los admitidos.
    """
    if transporte not in CLOUD_TRANSPORTES:
        raise RuntimeError(f"CLOUD_TRANSPORTE={transporte!r} no es válido: use redis o http.")
    return transporte


def leer_token_cloud(ruta: str | None = None) -> str:
    """Lee el token de nodo de su archivo (por defecto `.secrets/cloud_token.txt`).

    Args:
        ruta: archivo del token; por defecto `CLOUD_TOKEN_FILE`.

    Returns:
        El token, sin saltos de línea ni espacios al borde.

    Raises:
        RuntimeError: si el archivo no existe o está vacío. El mensaje nombra el archivo,
            nunca el contenido.
    """
    archivo = ruta or CLOUD_TOKEN_FILE
    try:
        with open(archivo, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        raise RuntimeError(
            f"CLOUD_TRANSPORTE=http exige el token de nodo en {archivo}: no se pudo leer "
            "(use `instalar_fog.sh importar-token <archivo>`)."
        ) from None
    if not token:
        raise RuntimeError(f"El archivo del token de nodo ({archivo}) está vacío.")
    return token


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
            "archivo vigente antes de arrancar (ver docs/manuales/GUIA_DESARROLLO.md, sección 5)."
        )
