# Entorno de Fog nativo (DEPLOY10). Se incluye con `. scripts/lib_fog_env.sh` desde fog_nativo.sh e
# instalar_fog.sh; no se ejecuta solo. Requiere que ENV_FILE ya se haya leído y que BACKEND_DIR esté definida.
#
# exportar_entorno_fog fija y exporta las variables que lee Fog (DATABASE_URL, REDIS_URL, rutas del modelo,
# FOG_DEVICE...). Variables opcionales: DATOS_DIR, DATASET_DIR, MODEL_RUN_ID, POSTGRES_HOST_PORT,
# REDIS_HOST_PORT, POSTGRES_DB_NAME, REDIS_URL_REMOTO, FOG_DEVICE.

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
