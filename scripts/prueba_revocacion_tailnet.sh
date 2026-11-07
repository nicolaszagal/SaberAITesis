#!/bin/sh
# Prototipo SEC02: mide cuánto tarda en cortarse el acceso al borrar un nodo en el panel de Tailscale.
#
# Uso, desde backend/: sh scripts/prueba_revocacion_tailnet.sh [segundos]   (por defecto 600)
# Une un contenedor sin TUN con la clave de .secrets/ts_authkey_cloud.txt, publica un Redis de
# prueba (TLS + ACL real) por `tailscale serve` y sondea cada 5 s imprimiendo la hora (UTC).
# Mientras corre: Admin console > Machines > borrar `ts-prueba-cloud` y anotar la hora.
set -eu

cd "$(dirname "$0")/.."
SEC="$(pwd)/.secrets"
TMP=$(mktemp -d)
DUR=${1:-600}
MAC=${TS_MAC_NOMBRE:-sabre-mac}
PIDS=""
trap 'for p in $PIDS; do kill "$p" 2>/dev/null || true; done
      docker rm -f ts-cloud-rev >/dev/null 2>&1 || true
      tailscale serve reset >/dev/null 2>&1 || true
      rm -rf "$TMP"' EXIT

[ "$(cut -c1-6 "$SEC/ts_authkey_cloud.txt")" = "tskey-" ] || { echo "Falta una clave válida en .secrets/ts_authkey_cloud.txt" >&2; exit 1; }
PASS_FOG=$(openssl rand -base64 48 | tr -d '\n=+/')
PASS_CLOUD=$(openssl rand -base64 48 | tr -d '\n=+/')
REDIS_PASSWORD_FOG=$PASS_FOG REDIS_PASSWORD_CLOUD=$PASS_CLOUD sh redis/generar_acl.sh "$TMP/users.acl"
redis-server --port 0 --tls-port 6390 --bind 127.0.0.1 \
    --tls-cert-file "$SEC/redis/server.crt" --tls-key-file "$SEC/redis/server.key" \
    --tls-ca-cert-file "$SEC/redis/ca.crt" --tls-auth-clients yes --tls-protocols TLSv1.3 \
    --aclfile "$TMP/users.acl" --save "" --appendonly no --dir "$TMP" >/dev/null 2>&1 &
PIDS="$PIDS $!"
sleep 1
tailscale serve --bg --tcp 6379 tcp://127.0.0.1:6390 >/dev/null

docker rm -f ts-cloud-rev >/dev/null 2>&1 || true
docker run -d --name ts-cloud-rev -e TS_HOSTNAME=ts-prueba-cloud -e TS_FORWARDS="6379:$MAC:6379" \
    -v "$SEC/ts_authkey_cloud.txt:/run/ts_authkey:ro" -e TS_AUTHKEY_FILE=/run/ts_authkey \
    -v "$SEC/redis:/pki:ro" -e REDISCLI_AUTH="$PASS_CLOUD" sabre-ts-prototipo sleep $((DUR + 60)) >/dev/null
for _ in $(seq 1 60); do docker logs ts-cloud-rev 2>&1 | grep -q 'tailnet lista' && break; sleep 1; done
docker logs ts-cloud-rev 2>&1 | grep -q 'tailnet lista' || { echo "El contenedor no se unió a la tailnet" >&2; exit 1; }

RC='redis-cli --tls --cacert /pki/ca.crt --cert /pki/cloud.crt --key /pki/cloud.key -h localhost -p 6379 --user cloud'
echo "$(date -u +%H:%M:%S) UNIDO: borre ahora el nodo ts-prueba-cloud en Machines y anote la hora"
fin=$(($(date +%s) + DUR))
primer_fallo=""
while [ "$(date +%s)" -lt "$fin" ]; do
    if docker exec ts-cloud-rev sh -c "timeout 4 $RC PING" 2>/dev/null | grep -q PONG; then
        echo "$(date -u +%H:%M:%S) acceso OK"
    else
        echo "$(date -u +%H:%M:%S) ACCESO CORTADO"
        [ -n "$primer_fallo" ] || primer_fallo=$(date -u +%H:%M:%S)
        # Tres cortes seguidos bastan: se confirma y se termina.
        n=$((${n:-0} + 1)); [ "$n" -ge 3 ] && break
    fi
    sleep 5
done
echo "Primer corte: ${primer_fallo:-ninguno en $DUR s}"
