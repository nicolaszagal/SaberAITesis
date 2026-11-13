#!/bin/sh
# Si hay certificados de cliente en base64 (despliegue remoto, DEPLOY07), los
# escribe en memoria (/dev/shm, permisos 600) y apunta REDIS_TLS_* a ellos.
# Sin las variables (Compose local) arranca sin cambios.
#
# DEPLOY09: con TS_AUTHKEY (clave efímera de Tailscale etiquetada tag:cloud) une el contenedor a la
# tailnet en modo userspace y abre un único reenviador, 127.0.0.1:6379 -> $TS_MAC_HOST:6379 (el
# Redis del Mac). La política de la tailnet solo deja a tag:cloud llegar a ese puerto. REDIS_URL
# apunta a rediss://cloud:...@localhost:6379/0. Nunca se imprime la clave.
set -eu

if [ -n "${TS_AUTHKEY:-}" ]; then
    SOCK=/tmp/tailscaled.sock
    tailscaled --tun=userspace-networking --statedir=/tmp/ts --socket="$SOCK" >/tmp/tailscaled.log 2>&1 &
    n=0
    until [ -S "$SOCK" ]; do
        n=$((n + 1))
        [ "$n" -lt 50 ] || { echo "tailscaled no arrancó" >&2; exit 1; }
        sleep 0.2
    done
    tailscale --socket="$SOCK" up --auth-key="$TS_AUTHKEY" --hostname="${TS_HOSTNAME:-sabre-cloud}" \
        --accept-dns=true --accept-routes=false >/dev/null
    unset TS_AUTHKEY
    socat "TCP-LISTEN:6379,bind=127.0.0.1,fork,reuseaddr" \
        "EXEC:tailscale --socket=$SOCK nc ${TS_MAC_HOST:-sabre-mac} 6379" &
    echo "tailnet lista: $(tailscale --socket="$SOCK" ip -4)"
fi

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
