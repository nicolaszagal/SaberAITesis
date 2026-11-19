# Entorno de Fog nativo (DEPLOY10). Se incluye con `. scripts/lib_fog_env.sh` desde fog_nativo.sh e
# instalar_fog.sh; no se ejecuta solo. Requiere que ENV_FILE ya se haya leído y que BACKEND_DIR esté definida.
#
# exportar_entorno_fog fija y exporta las variables que lee Fog (DATABASE_URL, REDIS_URL, rutas del modelo,
# FOG_DEVICE...). Variables opcionales: DATOS_DIR, DATASET_DIR, MODEL_RUN_ID, POSTGRES_HOST_PORT,
# REDIS_HOST_PORT, POSTGRES_DB_NAME, REDIS_URL_REMOTO (solo con MODO_REMOTO=1), FOG_DEVICE, SECRETS_DIR.

MODEL_RUN_ID_POR_DEFECTO=20260928_141021

exportar_entorno_fog() {
    POSTGRES_HOST_PORT=${POSTGRES_HOST_PORT:-5436}
    REDIS_HOST_PORT=${REDIS_HOST_PORT:-6380}
    DATOS_DIR=${DATOS_DIR:-./datos}
    mkdir -p "$DATOS_DIR/storage" "$DATOS_DIR/evidencia"
    DATOS_DIR=$(cd "$DATOS_DIR" && pwd)

    export DATABASE_URL="postgresql+asyncpg://sabre:${POSTGRES_PASSWORD:?falta POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_HOST_PORT}/${POSTGRES_DB_NAME:-sabre}"
    # DEPLOY07: con REDIS_URL_REMOTO (rediss://... hacia Railway) Fog no usa el Redis local.
    export REDIS_URL="${REDIS_URL_REMOTO:-redis://127.0.0.1:${REDIS_HOST_PORT}/0}"
    export STORAGE_DIR="$DATOS_DIR/storage"
    export EVIDENCE_DIR="$DATOS_DIR/evidencia"
    DS=${DATASET_DIR:-$BACKEND_DIR/../dataset}
    [ -d "$DS" ] && DS=$(cd "$DS" && pwd)
    export FEATURE_STATS_PATH="$DS/lstm_6class/feature_stats.npz"
    export FEATURE_PREPROCESSING_PROFILE=lstm_6class
    export YOLO_POSE_MODEL_PATH="$DS/yolov8x-pose.pt"
    MODEL_RUN_ID=${MODEL_RUN_ID:-$MODEL_RUN_ID_POR_DEFECTO}
    # DEPLOY10: dispositivo de YOLO explícito (cpu es lo que corrió en la Validación 1).
    export FOG_DEVICE="${FOG_DEVICE:-cpu}"
}

# --- Archivos de configuración -------------------------------------------------------------------
# MODO LOCAL POR DEFECTO. Con ENV_FILE explícito se usa solo ese archivo. Sin él se carga `.env` (si existe) y,
# SOLO con MODO_REMOTO=1 (la opción `--remoto` de fog_nativo.sh e instalar_fog.sh), encima el archivo de secretos
# del Mac, `.secrets/fog_remoto.env` (ENV_SECRETO): ahí viven AUTH_*, ENTORNO, REDIS_* y POSTGRES_DB_NAME de la
# configuración remota. Sin `--remoto` ese archivo no se lee, aunque exista.
#
# La contraseña de PostgreSQL tiene UNA sola fuente: `.secrets/postgres_password.txt` (SECRETS_DIR). Si el
# archivo existe manda sobre cualquier POSTGRES_PASSWORD de un `.env` (y avisa si difieren); si no existe, vale
# la de los `.env` (equipos sin `.secrets`).

# archivos_env: imprime, uno por línea, los archivos a cargar (los que existen).
archivos_env() {
    if [ -n "${ENV_FILE_EXPLICITO:-}" ]; then
        [ -f "$ENV_FILE" ] && printf '%s\n' "$ENV_FILE"
        return 0
    fi
    [ -f "$ENV_FILE" ] && printf '%s\n' "$ENV_FILE"
    if [ "${MODO_REMOTO:-0}" = 1 ] && [ -f "${ENV_SECRETO:-.secrets/fog_remoto.env}" ]; then
        printf '%s\n' "${ENV_SECRETO:-.secrets/fog_remoto.env}"
    fi
    return 0
}

# archivo_clave_postgres: ruta del archivo con la contraseña de PostgreSQL.
archivo_clave_postgres() {
    printf '%s' "${SECRETS_DIR:-.secrets}/postgres_password.txt"
}

# cargar_clave_postgres: exporta POSTGRES_PASSWORD desde `.secrets/postgres_password.txt` si existe.
cargar_clave_postgres() {
    _archivo=$(archivo_clave_postgres)
    [ -s "$_archivo" ] || return 0
    _valor=$(tr -d '\n\r' < "$_archivo")
    if [ -n "${POSTGRES_PASSWORD:-}" ] && [ "$POSTGRES_PASSWORD" != "$_valor" ]; then
        echo "AVISO: la POSTGRES_PASSWORD de los archivos .env no coincide con $_archivo; manda $_archivo (quite esa línea del .env)." >&2
    fi
    POSTGRES_PASSWORD=$_valor
    export POSTGRES_PASSWORD
}

# aplicar_modo: fija ENTORNO según el modo. Local por defecto; remoto solo con MODO_REMOTO=1. En local se
# ignoran las variables del modo remoto que hubiera en el entorno del shell (Redis de Railway, token de proxy).
aplicar_modo() {
    if [ "${MODO_REMOTO:-0}" = 1 ]; then
        ENTORNO=remoto
    else
        ENTORNO=local
        unset REDIS_URL_REMOTO PROXY_SHARED_TOKEN REDIS_TLS_CA REDIS_TLS_CERT REDIS_TLS_KEY
    fi
    export ENTORNO
}

# cargar_archivos_env: exporta las variables de todos los archivos de archivos_env, en orden, y después la
# contraseña de PostgreSQL de `.secrets`. No fija el modo: eso lo hace `aplicar_modo`.
cargar_archivos_env() {
    for archivo in $(archivos_env); do
        case "$archivo" in /*) ruta=$archivo ;; *) ruta=./$archivo ;; esac
        set -a
        . "$ruta"
        set +a
    done
    cargar_clave_postgres
    return 0
}
