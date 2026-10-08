#!/bin/sh
# Modo piloto (DOCK02): arranca Fog nativo (venv de GUIA_EJECUCION.md) contra
# PostgreSQL y Redis de Docker publicados en 127.0.0.1 por docker-compose.nativo.yml.
# Usa las mismas carpetas de datos que el modo Docker (backend/datos).
#
# Uso, desde backend/ y con el compose ya levantado:
#   docker compose -f docker-compose.yml -f docker-compose.nativo.yml up -d
#   sh scripts/fog_nativo.sh
#
# POSTGRES_DB_NAME elige otra base (por defecto sabre), p. ej. sabre_expo para el despliegue remoto.
# Variables opcionales: ENV_FILE (por defecto .env), DATOS_DIR (por defecto ./datos),
# MODEL_RUN_ID (por defecto el mismo run que fog/Dockerfile) y FOG_HOST_PORT (8001).
set -eu

cd "$(dirname "$0")/.."
BACKEND_DIR=$(pwd)

ENV_FILE=${ENV_FILE:-.env}
[ -f "$ENV_FILE" ] || { echo "Falta $ENV_FILE (cp .env.example .env)" >&2; exit 1; }
[ -f .venv/bin/activate ] || { echo "Falta .venv (ver GUIA_EJECUCION.md, sección 2)" >&2; exit 1; }
set -a
. "./$ENV_FILE"
set +a
. .venv/bin/activate

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
DS=$(cd "$BACKEND_DIR/../dataset" && pwd)
export FEATURE_STATS_PATH="$DS/lstm_6class/feature_stats.npz"
export FEATURE_PREPROCESSING_PROFILE=lstm_6class
export YOLO_POSE_MODEL_PATH="$DS/yolov8x-pose.pt"
MODEL_RUN_ID=${MODEL_RUN_ID:-20260928_141021}

DESTINOS="postgres:$POSTGRES_HOST_PORT"
[ -n "${REDIS_URL_REMOTO:-}" ] || DESTINOS="$DESTINOS redis:$REDIS_HOST_PORT"
for destino in $DESTINOS; do
    nc -z 127.0.0.1 "${destino#*:}" 2>/dev/null || {
        echo "${destino%%:*} no responde en 127.0.0.1:${destino#*:}. Levántelo con:" >&2
        echo "  docker compose -f docker-compose.yml -f docker-compose.nativo.yml up -d" >&2
        exit 1
    }
done

alembic upgrade head
python scripts/registrar_modelo.py "$MODEL_RUN_ID" --solo-si-no-hay-activo

exec uvicorn fog.main:app --host 0.0.0.0 --port "${FOG_HOST_PORT:-8001}"
