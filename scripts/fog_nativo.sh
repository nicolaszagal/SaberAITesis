#!/bin/sh
# Modo piloto (DOCK02): arranca Fog nativo (venv de docs/manuales/GUIA_INSTALACION.md) contra
# PostgreSQL y Redis de Docker publicados en 127.0.0.1 por docker-compose.nativo.yml.
# Usa las mismas carpetas de datos que el modo Docker (backend/datos).
#
# Uso, desde backend/ y con el compose ya levantado:
#   sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml up -d   (la contraseña de PostgreSQL sale de .secrets)
#   sh scripts/fog_nativo.sh              modo LOCAL (por defecto): solo .env, ENTORNO=local, sin bloqueo de `probar`
#   sh scripts/fog_nativo.sh --remoto     modo remoto: además .secrets/fog_remoto.env, ENTORNO=remoto y el
#                                         bloqueo (Fog solo arranca si la última `probar` pasó para este commit)
#   sh scripts/fog_nativo.sh --mostrar    (con o sin --remoto) muestra el modo, los archivos y el bloqueo y NO arranca
#
# POSTGRES_DB_NAME elige otra base (por defecto sabre), p. ej. sabre_expo para el despliegue remoto.
# Variables opcionales: ENV_FILE (por defecto .env y, si existe, .secrets/fog_remoto.env encima; ver lib_fog_env.sh), DATOS_DIR (por defecto ./datos),
# MODEL_RUN_ID (por defecto el mismo run que fog/Dockerfile), FOG_HOST_PORT (8001), VENV_DIR
# (por defecto .venv), DATASET_DIR (por defecto ../dataset) y FOG_BIND_HOST (ver
# scripts/lib_fog_bind.sh: en modo remoto Fog solo escucha en 127.0.0.1).
set -eu

cd "$(dirname "$0")/.."
BACKEND_DIR=$(pwd)

MODO_REMOTO=0
MOSTRAR=0
for argumento in "$@"; do
    case "$argumento" in
        --remoto) MODO_REMOTO=1 ;;
        --mostrar) MOSTRAR=1 ;;
        *) echo "Uso: sh scripts/fog_nativo.sh [--remoto] [--mostrar]" >&2; exit 2 ;;
    esac
done
export MODO_REMOTO

[ -z "${ENV_FILE:-}" ] || ENV_FILE_EXPLICITO=1
ENV_FILE=${ENV_FILE:-.env}
. scripts/lib_fog_env.sh
[ -n "$(archivos_env)" ] || { echo "Falta $ENV_FILE (cp .env.example .env) y no hay ${ENV_SECRETO:-.secrets/fog_remoto.env}" >&2; exit 1; }
VENV_DIR=${VENV_DIR:-.venv}
[ -f "$VENV_DIR/bin/activate" ] || { echo "Falta $VENV_DIR (corra: sh scripts/instalar_fog.sh instalar; ver docs/manuales/GUIA_INSTALACION.md)" >&2; exit 1; }
cargar_archivos_env
aplicar_modo
. "$VENV_DIR/bin/activate"
. scripts/lib_fog_bind.sh
BIND_HOST=$(fog_bind_host) || exit 1

exportar_entorno_fog

# DEPLOY10: en modo remoto (--remoto) Fog solo arranca si la última `probar` de este equipo pasó y es de este
# commit; con FOG_DEVICE distinto de cpu, también en local y con ese dispositivo.
REMOTO=""
[ "$MODO_REMOTO" = 1 ] && REMOTO="--remoto"
COMMIT=$(git rev-parse HEAD 2>/dev/null || echo desconocido)
if [ "$MOSTRAR" = 1 ]; then
    enmascarar() { printf '%s' "$1" | sed 's#//[^@/]*@#//***@#'; }
    echo "modo: $([ "$MODO_REMOTO" = 1 ] && echo remoto || echo local)"
    echo "ENTORNO=$ENTORNO"
    echo "BIND_HOST=$BIND_HOST"
    echo "archivos: $(archivos_env | tr '\n' ' ')"
    if usa_http; then
        echo "CLOUD_TRANSPORTE=http  CLOUD_URL=$CLOUD_URL  (sin Redis)"
        echo "CORS_ORIGINS=${CORS_ORIGINS:-}"
        echo "CLOUD_TOKEN_FILE=$CLOUD_TOKEN_FILE ($([ -s "$CLOUD_TOKEN_FILE" ] && echo presente || echo FALTA))"
    else
        echo "REDIS_URL=$(enmascarar "$REDIS_URL")"
    fi
    echo "DATABASE_URL=$(enmascarar "$DATABASE_URL")"
    echo "bloqueo: $([ -n "$REMOTO" ] && echo "exigido (--remoto)" || echo "solo si FOG_DEVICE no es cpu")"
fi
# shellcheck disable=SC2086
python scripts/instalador.py bloqueo --datos "$DATOS_DIR" --commit "$COMMIT" --dispositivo "$FOG_DEVICE" $REMOTO \
    || { echo "fog_nativo.sh no arranca. Corra: sh scripts/instalar_fog.sh probar$([ "$MODO_REMOTO" = 1 ] && echo ' --remoto')" >&2; exit 1; }
[ "$MOSTRAR" = 0 ] || exit 0

DESTINOS="postgres:$POSTGRES_HOST_PORT"
# Con Cloud por HTTP (DEPLOY11) Fog no usa Redis; con Redis remoto de Railway tampoco el local.
usa_http || [ -n "${REDIS_URL_REMOTO:-}" ] || DESTINOS="$DESTINOS redis:$REDIS_HOST_PORT"
if usa_http; then
    [ -s "$CLOUD_TOKEN_FILE" ] || { echo "Falta el token de nodo ($CLOUD_TOKEN_FILE). Instálelo con: sh scripts/instalar_fog.sh importar-token <archivo>" >&2; exit 1; }
fi
for destino in $DESTINOS; do
    nc -z 127.0.0.1 "${destino#*:}" 2>/dev/null || {
        echo "${destino%%:*} no responde en 127.0.0.1:${destino#*:}. Levántelo con:" >&2
        echo "  sh scripts/compose.sh $(archivos_compose) up -d" >&2
        exit 1
    }
done

# FIX03: avisa si hay revisiones sin respaldar de una sesión anterior (no detiene el arranque).
ENV_FILE="$ENV_FILE" sh scripts/recordar_respaldo.sh || true

alembic upgrade head
python scripts/registrar_modelo.py "$MODEL_RUN_ID" --solo-si-no-hay-activo --dataset-dir "$DS/lstm_6class"

exec uvicorn fog.main:app --host "$BIND_HOST" --port "${FOG_HOST_PORT:-8001}"
