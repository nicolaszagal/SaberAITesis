#!/bin/sh
# Acceso remoto temporal para la prueba del árbitro (DEPLOY03).
#
# Uso, desde backend/ y con Fog nativo ya corriendo (scripts/fog_nativo.sh):
#   sh scripts/prueba_remota.sh start   # proxy + túnel Cloudflare; imprime la URL
#   sh scripts/prueba_remota.sh stop    # cierra túnel y proxy
#
# Variables opcionales: FOG_HOST_PORT (8001), CLIP_MAX_MB (por defecto el de
# shared/config.py) y FRONTEND_DIST. Ver docs/manuales/PRUEBA_REMOTA.md.
set -eu

cd "$(dirname "$0")/.."
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose -f docker-compose.remoto.yml"
else
    COMPOSE="docker-compose -f docker-compose.remoto.yml"
fi
PUERTO_PROXY=8090
URL_FILE=datos/prueba_remota_url.txt
PID_FILE=datos/prueba_remota_tunel.pid
LOG_FILE=datos/prueba_remota_tunel.log

detener_tunel() {
    if [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
}

iniciar() {
    command -v cloudflared >/dev/null 2>&1 || {
        echo "cloudflared no está instalado. Instálelo con: brew install cloudflared" >&2
        exit 1
    }
    [ -f .secrets/htpasswd ] || {
        echo "Falta .secrets/htpasswd (ver docs/manuales/PRUEBA_REMOTA.md, sección 3)" >&2
        exit 1
    }
    DIST=${FRONTEND_DIST:-../SaberAISoftware/dist-remoto}
    [ -f "$DIST/index.html" ] || {
        echo "Falta el build del frontend en $DIST (npm run build:remoto en SaberAISoftware)" >&2
        exit 1
    }
    FOG_PORT=${FOG_HOST_PORT:-8001}
    curl -fsS -m 5 "http://127.0.0.1:$FOG_PORT/health" >/dev/null || {
        echo "Fog no responde en http://127.0.0.1:$FOG_PORT/health. Levántelo con: sh scripts/fog_nativo.sh" >&2
        exit 1
    }
    if [ -z "${CLIP_MAX_MB:-}" ]; then
        # Mismo valor que usa Fog: shared/config.py (admite decimales; nginx pide entero).
        CLIP_MAX_MB=$(.venv/bin/python -c "import math; from shared import config; print(math.ceil(config.CLIP_MAX_MB))")
    fi
    export CLIP_MAX_MB FOG_UPSTREAM="host.docker.internal:$FOG_PORT"

    mkdir -p datos
    detener_tunel
    $COMPOSE up -d proxy
    n=0
    until curl -s -m 2 -o /dev/null "http://127.0.0.1:$PUERTO_PROXY/"; do
        n=$((n + 1))
        [ "$n" -lt 15 ] || { echo "El proxy no responde en 127.0.0.1:$PUERTO_PROXY" >&2; exit 1; }
        sleep 1
    done

    : > "$LOG_FILE"
    cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PUERTO_PROXY" >"$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    n=0
    URL=""
    while [ -z "$URL" ]; do
        URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG_FILE" | head -n 1 || true)
        n=$((n + 1))
        if [ -z "$URL" ] && [ "$n" -ge 30 ]; then
            echo "El túnel no entregó una URL en 30 s. Revise $LOG_FILE" >&2
            detener
            exit 1
        fi
        [ -n "$URL" ] || sleep 1
    done
    echo "$URL" > "$URL_FILE"
    echo "URL de la prueba remota: $URL"
    echo "Guardada en $URL_FILE. Para terminar: sh scripts/prueba_remota.sh stop"
}

detener() {
    detener_tunel
    $COMPOSE down
    rm -f "$URL_FILE"
    echo "Túnel y proxy detenidos."
}

case "${1:-}" in
    start) iniciar ;;
    stop) detener ;;
    *) echo "Uso: sh scripts/prueba_remota.sh {start|stop}" >&2; exit 2 ;;
esac
