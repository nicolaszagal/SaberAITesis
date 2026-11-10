#!/bin/sh
# Redis nativo del despliegue remoto (SEC02): TLS 1.3 + mTLS + ACL por nodo, solo en 127.0.0.1.
#
# Uso, desde backend/:
#   sh scripts/redis_nativo.sh start     # arranca en 127.0.0.1:$REDIS_PUERTO_NATIVO (6390)
#   sh scripts/redis_nativo.sh stop
#   sh scripts/redis_nativo.sh status
#
# Es el Redis que ve la nube: scripts/fog_remoto.sh lo publica en la tailnet solo mientras dura la
# ventana de acceso. El Redis de Homebrew (6379, sin TLS ni usuarios) no se toca: es de desarrollo.
# Requiere .secrets/redis/ con la PKI y las contraseñas de scripts/rotar_secretos.sh. Los usuarios
# `fog` y `cloud` se generan con redis/generar_acl.sh (mismos permisos que en las pruebas de ACL).
#
# Variables opcionales: SECRETS_DIR (.secrets), DATOS_DIR (datos), REDIS_PUERTO_NATIVO (6390) y
# REDIS_SERVER (redis-server).
set -eu

cd "$(dirname "$0")/.."
SECRETS_DIR=${SECRETS_DIR:-.secrets}
DATOS_DIR=${DATOS_DIR:-datos}
PUERTO=${REDIS_PUERTO_NATIVO:-6390}
SERVIDOR=${REDIS_SERVER:-redis-server}
ESTADO="$DATOS_DIR/redis_nativo"
PID_FILE="$ESTADO/redis.pid"
LOG_FILE="$ESTADO/redis.log"

vivo() {
    [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

iniciar() {
    command -v "$SERVIDOR" >/dev/null 2>&1 || { echo "No se encontró $SERVIDOR (brew install redis)." >&2; exit 1; }
    for f in ca.crt server.crt server.key redis_password_fog.txt redis_password_cloud.txt; do
        [ -s "$SECRETS_DIR/redis/$f" ] || {
            echo "Falta $SECRETS_DIR/redis/$f: corra sh scripts/rotar_secretos.sh (o --forzar)." >&2
            exit 1
        }
    done
    vivo && { echo "Redis nativo ya corre en 127.0.0.1:$PUERTO."; return 0; }
    nc -z 127.0.0.1 "$PUERTO" 2>/dev/null && { echo "El puerto $PUERTO ya está ocupado." >&2; exit 1; }

    umask 077
    mkdir -p "$ESTADO"
    chmod 700 "$ESTADO"
    REDIS_PASSWORD_FOG=$(cat "$SECRETS_DIR/redis/redis_password_fog.txt") \
    REDIS_PASSWORD_CLOUD=$(cat "$SECRETS_DIR/redis/redis_password_cloud.txt") \
        sh redis/generar_acl.sh "$ESTADO/users.acl"
    RAIZ=$(cd "$SECRETS_DIR" && pwd)
    # Rutas absolutas: --dir cambia el directorio de trabajo antes de leer los certificados.
    nohup "$SERVIDOR" --port 0 --tls-port "$PUERTO" --bind 127.0.0.1 --protected-mode yes \
        --tls-cert-file "$RAIZ/redis/server.crt" --tls-key-file "$RAIZ/redis/server.key" \
        --tls-ca-cert-file "$RAIZ/redis/ca.crt" --tls-auth-clients yes --tls-protocols TLSv1.3 \
        --aclfile "$(cd "$ESTADO" && pwd)/users.acl" --save "" --appendonly no \
        --maxmemory 200mb --maxmemory-policy noeviction \
        --dir "$(cd "$ESTADO" && pwd)" >"$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    n=0
    until nc -z 127.0.0.1 "$PUERTO" 2>/dev/null; do
        n=$((n + 1))
        if [ "$n" -ge 50 ] || ! vivo; then
            echo "Redis no arrancó. Últimas líneas de $LOG_FILE:" >&2
            tail -3 "$LOG_FILE" >&2
            rm -f "$PID_FILE"
            exit 1
        fi
        sleep 0.2
    done
    echo "Redis nativo (TLS + ACL) en 127.0.0.1:$PUERTO"
}

detener() {
    if vivo; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        n=0
        while vivo && [ "$n" -lt 25 ]; do n=$((n + 1)); sleep 0.2; done
    fi
    rm -f "$PID_FILE" "$ESTADO/users.acl"
    echo "Redis nativo detenido."
}

estado() {
    if vivo; then
        echo "Redis nativo activo en 127.0.0.1:$PUERTO (pid $(cat "$PID_FILE"))."
    else
        echo "Redis nativo detenido."
    fi
}

case "${1:-}" in
    start) iniciar ;;
    stop) detener ;;
    status) estado ;;
    *) echo "Uso: sh scripts/redis_nativo.sh {start|stop|status}" >&2; exit 2 ;;
esac
