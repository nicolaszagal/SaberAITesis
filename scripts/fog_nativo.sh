#!/bin/sh
# Modo piloto (DOCK02): arranca Fog nativo (venv de GUIA_EJECUCION.md) contra
# PostgreSQL y Redis de Docker publicados en 127.0.0.1 por docker-compose.nativo.yml.
# Usa las mismas carpetas de datos que el modo Docker (backend/datos).
#
# Uso, desde backend/ y con el compose ya levantado:
#   docker compose -f docker-compose.yml -f docker-compose.nativo.yml up -d   (o docker-compose, según el equipo)
#   sh scripts/fog_nativo.sh
#
# POSTGRES_DB_NAME elige otra base (por defecto sabre), p. ej. sabre_expo para el despliegue remoto.
# Variables opcionales: ENV_FILE (por defecto .env y, si existe, .secrets/fog_remoto.env encima; ver lib_fog_env.sh), DATOS_DIR (por defecto ./datos),
# MODEL_RUN_ID (por defecto el mismo run que fog/Dockerfile), FOG_HOST_PORT (8001), VENV_DIR
# (por defecto .venv), DATASET_DIR (por defecto ../dataset) y FOG_BIND_HOST (ver
# scripts/lib_fog_bind.sh: en modo remoto Fog solo escucha en 127.0.0.1).
set -eu

cd "$(dirname "$0")/.."
BACKEND_DIR=$(pwd)

[ -z "${ENV_FILE:-}" ] || ENV_FILE_EXPLICITO=1
ENV_FILE=${ENV_FILE:-.env}
. scripts/lib_fog_env.sh
[ -n "$(archivos_env)" ] || { echo "Falta $ENV_FILE (cp .env.example .env) y no hay ${ENV_SECRETO:-.secrets/fog_remoto.env}" >&2; exit 1; }
VENV_DIR=${VENV_DIR:-.venv}
[ -f "$VENV_DIR/bin/activate" ] || { echo "Falta $VENV_DIR (ver GUIA_EJECUCION.md, sección 2)" >&2; exit 1; }
cargar_archivos_env
. "$VENV_DIR/bin/activate"
. scripts/lib_fog_bind.sh
BIND_HOST=$(fog_bind_host) || exit 1

exportar_entorno_fog

# EDGE02: token de servicio de Edge (scripts/crear_edge_token.sh); el entorno manda sobre el archivo.
[ -n "${EDGE_TOKEN:-}" ] || { [ -s .secrets/edge_token.txt ] && EDGE_TOKEN=$(cat .secrets/edge_token.txt) && export EDGE_TOKEN; } || true

# DEPLOY10: en modo remoto (ENTORNO=remoto) Fog solo arranca si la última `probar` de este equipo pasó
# y es de este commit; con FOG_DEVICE distinto de cpu, también en local y con ese dispositivo.
REMOTO=""
[ "${ENTORNO:-}" = "remoto" ] && REMOTO="--remoto"
COMMIT=$(git rev-parse HEAD 2>/dev/null || echo desconocido)
# shellcheck disable=SC2086
python scripts/instalador.py bloqueo --datos "$DATOS_DIR" --commit "$COMMIT" --dispositivo "$FOG_DEVICE" $REMOTO \
    || { echo "fog_nativo.sh no arranca. Corra: sh scripts/instalar_fog.sh probar" >&2; exit 1; }

DESTINOS="postgres:$POSTGRES_HOST_PORT"
[ -n "${REDIS_URL_REMOTO:-}" ] || DESTINOS="$DESTINOS redis:$REDIS_HOST_PORT"
for destino in $DESTINOS; do
    nc -z 127.0.0.1 "${destino#*:}" 2>/dev/null || {
        echo "${destino%%:*} no responde en 127.0.0.1:${destino#*:}. Levántelo con:" >&2
        echo "  docker compose (o docker-compose) -f docker-compose.yml -f docker-compose.nativo.yml up -d" >&2
        exit 1
    }
done

# FIX03: avisa si hay revisiones sin respaldar de una sesión anterior (no detiene el arranque).
ENV_FILE="$ENV_FILE" sh scripts/recordar_respaldo.sh || true

alembic upgrade head
python scripts/registrar_modelo.py "$MODEL_RUN_ID" --solo-si-no-hay-activo

exec uvicorn fog.main:app --host "$BIND_HOST" --port "${FOG_HOST_PORT:-8001}"
