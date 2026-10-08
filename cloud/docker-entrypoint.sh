#!/bin/sh
# Si hay certificados de cliente en base64 (despliegue remoto, DEPLOY07), los
# escribe en memoria (/dev/shm, permisos 600) y apunta REDIS_TLS_* a ellos.
# Sin las variables (Compose local) arranca sin cambios.
set -eu

if [ -n "${REDIS_TLS_CA_B64:-}" ]; then
    DIR=/dev/shm/redis-tls
    umask 077
    mkdir -p "$DIR"
    printf '%s' "$REDIS_TLS_CA_B64" | base64 -d > "$DIR/ca.crt"
    printf '%s' "$REDIS_TLS_CERT_B64" | base64 -d > "$DIR/client.crt"
    printf '%s' "$REDIS_TLS_KEY_B64" | base64 -d > "$DIR/client.key"
    export REDIS_TLS_CA="$DIR/ca.crt" REDIS_TLS_CERT="$DIR/client.crt" REDIS_TLS_KEY="$DIR/client.key"
    unset REDIS_TLS_CA_B64 REDIS_TLS_CERT_B64 REDIS_TLS_KEY_B64
fi
exec "$@"
