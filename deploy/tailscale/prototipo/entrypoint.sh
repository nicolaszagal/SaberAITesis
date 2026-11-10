#!/bin/sh
# Une el contenedor a la tailnet en modo userspace y abre reenviadores locales.
# Variables: TS_AUTHKEY o TS_AUTHKEY_FILE (clave efímera y etiquetada), TS_HOSTNAME y
# TS_FORWARDS ("puertoLocal:host:puertoRemoto ..."). Nunca se imprime la clave.
set -eu

if [ -z "${TS_AUTHKEY:-}" ] && [ -n "${TS_AUTHKEY_FILE:-}" ]; then
    TS_AUTHKEY=$(cat "$TS_AUTHKEY_FILE")
fi
[ -n "${TS_AUTHKEY:-}" ] || { echo "Falta TS_AUTHKEY o TS_AUTHKEY_FILE" >&2; exit 1; }
SOCK=/tmp/tailscaled.sock

tailscaled --tun=userspace-networking --statedir=/tmp/ts --socket="$SOCK" >/tmp/tailscaled.log 2>&1 &
for _ in $(seq 1 50); do [ -S "$SOCK" ] && break; sleep 0.2; done
tailscale --socket="$SOCK" up --auth-key="$TS_AUTHKEY" --hostname="${TS_HOSTNAME:-sabre-prototipo}" \
    --accept-dns=true --accept-routes=false >/dev/null
unset TS_AUTHKEY

for par in ${TS_FORWARDS:-}; do
    local_port=${par%%:*}
    resto=${par#*:}
    socat "TCP-LISTEN:$local_port,bind=127.0.0.1,fork,reuseaddr" \
        "EXEC:tailscale --socket=$SOCK nc ${resto%%:*} ${resto#*:}" &
done
echo "tailnet lista: $(tailscale --socket="$SOCK" ip -4)"
exec "$@"
