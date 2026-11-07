#!/bin/sh
# Túnel de Fog para el despliegue remoto (DEPLOY07), con ventana de tiempo (SEC02).
#
# Uso, desde backend/ y con Fog nativo ya corriendo en modo remoto
# (ENTORNO=remoto, AUTH_*, PROXY_SHARED_TOKEN, REDIS_URL=rediss://... y REDIS_TLS_*):
#   sh scripts/fog_remoto.sh start --horas N   # N de 1 a 8: abre el túnel y lo cierra solo al vencer
#   sh scripts/fog_remoto.sh stop              # cierra el túnel, caffeinate y el vigía; avisa si falta respaldar (FIX03)
#   sh scripts/fog_remoto.sh status            # estado y tiempo restante
#
# El túnel apunta directo a Fog (no a un proxy local). Con trycloudflare la URL
# cambia en cada arranque: hay que actualizar FOG_UPSTREAM en Railway y reiniciar
# el frontend. Requiere PROXY_SHARED_TOKEN en el entorno (Fog responde 403 sin él).
#
# Solo para pruebas: FOG_REMOTO_SEGUNDOS_POR_HORA (3600) y FOG_REMOTO_SONDEO_S (5).
set -eu

cd "$(dirname "$0")/.."
SCRIPT="$(pwd)/scripts/$(basename "$0")"
FOG_PORT=${FOG_HOST_PORT:-8001}
URL_FILE=datos/fog_remoto_url.txt
PID_TUNEL=datos/fog_remoto_tunel.pid
PID_CAFE=datos/fog_remoto_caffeinate.pid
PID_VIGIA=datos/fog_remoto_vigia.pid
VENCE_FILE=datos/fog_remoto_vence.txt
LOG_FILE=datos/fog_remoto_tunel.log
SEG_POR_HORA=${FOG_REMOTO_SEGUNDOS_POR_HORA:-3600}
SONDEO_S=${FOG_REMOTO_SONDEO_S:-5}
HORAS_MIN=1
HORAS_MAX=8

matar() {
    if [ -f "$1" ]; then
        kill "$(cat "$1")" 2>/dev/null || true
        rm -f "$1"
    fi
}

hora_de() { # epoch -> HH:MM local (BSD y GNU)
    date -r "$1" '+%H:%M' 2>/dev/null || date -d "@$1" '+%H:%M'
}

duracion() { # segundos -> "H h M min"
    printf '%s h %s min' "$(($1 / 3600))" "$((($1 % 3600) / 60))"
}

avisar_restos() {
    # Si quedan archivos del arranque anterior, el último `stop` no corrió (el túnel
    # de 10/10/2026 siguió abierto 11 días por eso).
    for f in "$URL_FILE" "$PID_TUNEL" "$PID_CAFE" "$PID_VIGIA" "$VENCE_FILE"; do
        if [ -f "$f" ]; then
            desde=$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f" 2>/dev/null || stat -c '%y' "$f" | cut -c1-16)
            echo "AVISO: quedaban archivos de un túnel anterior ($f, $desde): el último 'stop' no corrió." >&2
            return 0
        fi
    done
}

iniciar() {
    horas=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --horas) horas="${2:-}"; shift 2 || shift ;;
            --horas=*) horas="${1#--horas=}"; shift ;;
            *) echo "Argumento desconocido: $1" >&2; exit 2 ;;
        esac
    done
    case "$horas" in
        ''|*[!0-9]*)
            echo "Falta --horas N (entero de $HORAS_MIN a $HORAS_MAX): el túnel debe tener ventana." >&2
            exit 2 ;;
    esac
    if [ "$horas" -lt "$HORAS_MIN" ] || [ "$horas" -gt "$HORAS_MAX" ]; then
        echo "--horas debe estar entre $HORAS_MIN y $HORAS_MAX (recibido: $horas)." >&2
        exit 2
    fi

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
    avisar_restos
    matar "$PID_VIGIA"
    matar "$PID_TUNEL"
    matar "$PID_CAFE"
    rm -f "$VENCE_FILE"

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
    caffeinate -s -i >/dev/null 2>&1 &
    echo $! > "$PID_CAFE"

    # Vigía: cierra el túnel al vencer la ventana, aunque nadie ejecute `stop`.
    vence=$(($(date +%s) + horas * SEG_POR_HORA))
    echo "$vence" > "$VENCE_FILE"
    nohup sh -c '
        while [ "$(date +%s)" -lt "$1" ]; do sleep "$3"; done
        exec sh "$2" vencer
    ' vigia "$vence" "$SCRIPT" "$SONDEO_S" >/dev/null 2>&1 &
    echo $! > "$PID_VIGIA"

    echo "URL del túnel de Fog: $URL"
    echo "El túnel se cierra solo a las $(hora_de "$vence") ($horas h)."
    echo "Siguiente paso: actualizar FOG_UPSTREAM=${URL#https://} en el servicio frontend de Railway y reiniciarlo."
    echo "La URL cambia en cada arranque. Para terminar antes: sh scripts/fog_remoto.sh stop"
}

detener() {
    matar "$PID_VIGIA"
    matar "$PID_TUNEL"
    matar "$PID_CAFE"
    rm -f "$URL_FILE" "$VENCE_FILE"
    echo "Túnel y caffeinate detenidos."
    # FIX03: recuerda respaldar si hubo revisiones nuevas (POSTGRES_DB_NAME=sabre_expo en el remoto).
    sh scripts/recordar_respaldo.sh || true
}

vencer() {
    # Lo llama el vigía: su propio PID ya no debe matarse a sí mismo.
    rm -f "$PID_VIGIA"
    echo "Ventana vencida: cerrando el túnel."
    detener
}

estado() {
    if [ -f "$PID_TUNEL" ] && kill -0 "$(cat "$PID_TUNEL")" 2>/dev/null; then
        url=$(cat "$URL_FILE" 2>/dev/null || echo 'URL desconocida')
        if [ -f "$VENCE_FILE" ]; then
            vence=$(cat "$VENCE_FILE")
            resta=$((vence - $(date +%s)))
            if [ "$resta" -gt 0 ]; then
                echo "Túnel activo: $url. Quedan $(duracion "$resta") (vence a las $(hora_de "$vence"))."
            else
                echo "Túnel activo: $url. VENCIDO hace $(duracion $((-resta))): ejecute 'stop'."
            fi
        else
            echo "Túnel activo: $url. SIN ventana registrada: ejecute 'stop' y vuelva a abrirlo con --horas."
        fi
    elif [ -f "$PID_TUNEL" ] || [ -f "$URL_FILE" ]; then
        echo "Túnel detenido, pero quedan archivos viejos: el último 'stop' no corrió."
    else
        echo "Túnel detenido."
    fi
}

case "${1:-}" in
    start) shift; iniciar "$@" ;;
    stop) detener ;;
    vencer) vencer ;;
    status) estado ;;
    *) echo "Uso: sh scripts/fog_remoto.sh {start --horas N|stop|status}" >&2; exit 2 ;;
esac
