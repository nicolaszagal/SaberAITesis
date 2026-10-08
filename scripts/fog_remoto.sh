#!/bin/sh
# Túnel de Fog para el despliegue remoto (DEPLOY07).
#
# Uso, desde backend/ y con Fog nativo ya corriendo en modo remoto
# (ENTORNO=remoto, AUTH_*, PROXY_SHARED_TOKEN, REDIS_URL=rediss://... y REDIS_TLS_*):
#   sh scripts/fog_remoto.sh start    # verifica /health, abre el túnel hacia Fog, imprime la URL
#   sh scripts/fog_remoto.sh stop     # cierra el túnel y caffeinate
#   sh scripts/fog_remoto.sh status
#
# El túnel apunta directo a Fog (no a un proxy local). Con trycloudflare la URL
# cambia en cada arranque: hay que actualizar FOG_UPSTREAM en Railway y reiniciar
# el frontend. Requiere PROXY_SHARED_TOKEN en el entorno (Fog responde 403 sin él).
set -eu

cd "$(dirname "$0")/.."
FOG_PORT=${FOG_HOST_PORT:-8001}
URL_FILE=datos/fog_remoto_url.txt
PID_TUNEL=datos/fog_remoto_tunel.pid
PID_CAFE=datos/fog_remoto_caffeinate.pid
LOG_FILE=datos/fog_remoto_tunel.log

matar() {
    if [ -f "$1" ]; then
        kill "$(cat "$1")" 2>/dev/null || true
        rm -f "$1"
    fi
}

iniciar() {
    command -v cloudflared >/dev/null 2>&1 || {
        echo "cloudflared no está instalado. Instálelo con: brew install cloudflared" >&2
        exit 1
    }
    [ -n "${PROXY_SHARED_TOKEN:-}" ] || {
        echo "Defina PROXY_SHARED_TOKEN (el mismo valor que en Railway)." >&2
        exit 1
    }
    curl -fsS -m 5 -H "X-Proxy-Token: $PROXY_SHARED_TOKEN" "http://127.0.0.1:$FOG_PORT/health" >/dev/null || {
        echo "Fog no responde en http://127.0.0.1:$FOG_PORT/health. Levántelo con: sh scripts/fog_nativo.sh" >&2
        exit 1
    }
    mkdir -p datos
    matar "$PID_TUNEL"
    matar "$PID_CAFE"

    : > "$LOG_FILE"
    cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$FOG_PORT" >"$LOG_FILE" 2>&1 &
    echo $! > "$PID_TUNEL"
    n=0
    URL=""
    while [ -z "$URL" ]; do
        URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG_FILE" | head -n 1 || true)
        n=$((n + 1))
        if [ -z "$URL" ] && [ "$n" -ge 30 ]; then
            echo "El túnel no entregó una URL en 30 s. Revise $LOG_FILE" >&2
            matar "$PID_TUNEL"
            exit 1
        fi
        [ -n "$URL" ] || sleep 1
    done
    echo "$URL" > "$URL_FILE"

    # Evita que el Mac se suspenda solo mientras dura la ventana de uso.
    caffeinate -s -i &
    echo $! > "$PID_CAFE"

    echo "URL del túnel de Fog: $URL"
    echo "Siguiente paso: actualizar FOG_UPSTREAM=${URL#https://} en el servicio frontend de Railway y reiniciarlo."
    echo "La URL cambia en cada arranque. Para terminar: sh scripts/fog_remoto.sh stop"
}

detener() {
    matar "$PID_TUNEL"
    matar "$PID_CAFE"
    rm -f "$URL_FILE"
    echo "Túnel y caffeinate detenidos."
}

estado() {
    if [ -f "$PID_TUNEL" ] && kill -0 "$(cat "$PID_TUNEL")" 2>/dev/null; then
        echo "Túnel activo: $(cat "$URL_FILE" 2>/dev/null || echo 'URL desconocida')"
    else
        echo "Túnel detenido."
    fi
}

case "${1:-}" in
    start) iniciar ;;
    stop) detener ;;
    status) estado ;;
    *) echo "Uso: sh scripts/fog_remoto.sh {start|stop|status}" >&2; exit 2 ;;
esac
