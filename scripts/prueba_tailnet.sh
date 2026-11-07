#!/bin/sh
# Prototipo SEC02: ¿un contenedor sin TUN (como Railway) alcanza Redis y Fog del Mac por la tailnet?
#
# Uso, desde backend/, con Tailscale ya instalado y el Mac unido a la tailnet con tag:mac:
#   sh scripts/prueba_tailnet.sh
# Requiere .secrets/ts_authkey_cloud.txt y .secrets/ts_authkey_frontend.txt (claves efímeras,
# etiquetadas, de corta duración) y .secrets/redis/ (PKI de SEC01). No imprime secretos.
# Levanta un Redis de prueba (TLS + ACL real, puerto 6390) y un sumidero HTTP (8001), ambos en
# 127.0.0.1, los publica con `tailscale serve` y los prueba desde dos contenedores.
set -eu

cd "$(dirname "$0")/.."
SEC="$(pwd)/.secrets"
PROTO=deploy/tailscale/prototipo
TMP=$(mktemp -d)
MB=${PRUEBA_MB:-200}
MAC=${TS_MAC_NOMBRE:-sabre-mac}
PIDS=""
trap 'for p in $PIDS; do kill "$p" 2>/dev/null || true; done
      docker rm -f ts-cloud ts-frontend >/dev/null 2>&1 || true
      tailscale serve reset >/dev/null 2>&1 || true
      rm -rf "$TMP"' EXIT

for f in "$SEC/ts_authkey_cloud.txt" "$SEC/ts_authkey_frontend.txt" "$SEC/redis/ca.crt" "$SEC/redis/server.crt" "$SEC/redis/server.key"; do
    [ -s "$f" ] || { echo "Falta $f" >&2; exit 1; }
done
for f in "$SEC/ts_authkey_cloud.txt" "$SEC/ts_authkey_frontend.txt"; do
    case "$(cut -c1-6 "$f")" in
        tskey-) ;;
        *) echo "$f no tiene formato de clave de Tailscale (debe empezar por tskey-). Copie la clave en el panel y recién ahí ejecute pbpaste." >&2; exit 1 ;;
    esac
done
tailscale status >/dev/null 2>&1 || { echo "Tailscale no está conectado en el Mac." >&2; exit 1; }

# 1. Redis de prueba con la ACL real y TLS 1.3 + mTLS
PASS_FOG=$(openssl rand -base64 48 | tr -d '\n=+/')
PASS_CLOUD=$(openssl rand -base64 48 | tr -d '\n=+/')
REDIS_PASSWORD_FOG=$PASS_FOG REDIS_PASSWORD_CLOUD=$PASS_CLOUD sh redis/generar_acl.sh "$TMP/users.acl"
redis-server --port 0 --tls-port 6390 --bind 127.0.0.1 \
    --tls-cert-file "$SEC/redis/server.crt" --tls-key-file "$SEC/redis/server.key" \
    --tls-ca-cert-file "$SEC/redis/ca.crt" --tls-auth-clients yes --tls-protocols TLSv1.3 \
    --aclfile "$TMP/users.acl" --save "" --appendonly no --dir "$TMP" >/dev/null 2>&1 &
PIDS="$PIDS $!"

# 2. Sumidero HTTP y reenvío por la tailnet (los servicios solo escuchan en 127.0.0.1)
python3 "$PROTO/sumidero.py" 8001 &
PIDS="$PIDS $!"
sleep 1
tailscale serve --bg --tcp 6379 tcp://127.0.0.1:6390 >/dev/null
tailscale serve --bg --tcp 8001 tcp://127.0.0.1:8001 >/dev/null

# 3. Dos contenedores sin NET_ADMIN ni /dev/net/tun
head -c $((MB * 1024 * 1024)) /dev/urandom > "$TMP/clip.bin"
SHA_LOCAL=$(shasum -a 256 "$TMP/clip.bin" | cut -d' ' -f1)
docker run -d --name ts-cloud -e TS_HOSTNAME=ts-prueba-cloud -e TS_FORWARDS="6379:$MAC:6379" \
    -v "$SEC/ts_authkey_cloud.txt:/run/ts_authkey:ro" -e TS_AUTHKEY_FILE=/run/ts_authkey \
    -v "$SEC/redis:/pki:ro" -e REDISCLI_AUTH="$PASS_CLOUD" \
    sabre-ts-prototipo sleep 600 >/dev/null
docker run -d --name ts-frontend -e TS_HOSTNAME=ts-prueba-frontend -e TS_FORWARDS="8001:$MAC:8001" \
    -v "$SEC/ts_authkey_frontend.txt:/run/ts_authkey:ro" -e TS_AUTHKEY_FILE=/run/ts_authkey \
    sabre-ts-prototipo sleep 600 >/dev/null
# docker cp y no un montaje: colima solo comparte el home con la VM, no /var/folders.
docker cp "$TMP/clip.bin" ts-frontend:/clip.bin
echo "Uniendo los contenedores a la tailnet (hasta 60 s cada uno)..."
for c in ts-cloud ts-frontend; do
    for _ in $(seq 1 60); do
        docker logs "$c" 2>&1 | grep -q 'tailnet lista' && break
        docker ps -q -f "name=$c" | grep -q . || break  # el contenedor terminó: no esperar más
        sleep 1
    done
    docker logs "$c" 2>&1 | grep -q 'tailnet lista' || { echo "$c no se unió a la tailnet"; docker logs "$c" 2>&1 | sed -E 's/tskey-[A-Za-z0-9-]+/<oculto>/g' | tail -5; exit 1; }
done

echo "== Redis (tag:cloud -> mac:6379, TLS + ACL del usuario cloud) =="
RC='redis-cli --tls --cacert /pki/ca.crt --cert /pki/cloud.crt --key /pki/cloud.key -h localhost -p 6379 --user cloud'
docker exec ts-cloud sh -c "$RC PING"
docker exec ts-cloud sh -c "$RC XADD cloud:verdicts:prueba '*' a b" | sed 's/^/XADD permitido: /'
docker exec ts-cloud sh -c "$RC XADD fog:features '*' a b" 2>&1 | sed 's/^/XADD en fog:features (debe ser NOPERM): /'
docker exec ts-cloud sh -c 'i=0; s=$(date +%s%N); while [ $i -lt 50 ]; do '"$RC"' PING >/dev/null; i=$((i+1)); done; e=$(date +%s%N); echo "50 PING con handshake TLS: $(( (e-s)/50000000 )) ms cada uno"'

echo "== Fog (tag:frontend -> mac:8001) =="
docker exec ts-frontend sh -c 'i=0; s=$(date +%s%N); while [ $i -lt 50 ]; do curl -s http://127.0.0.1:8001/ >/dev/null; i=$((i+1)); done; e=$(date +%s%N); echo "50 GET pequeños: $(( (e-s)/50000000 )) ms cada uno"'
INICIO=$(date +%s)
RESP=$(docker exec ts-frontend curl -s -m 600 -X POST --data-binary @/clip.bin -H 'Content-Type: application/octet-stream' http://127.0.0.1:8001/)
FIN=$(date +%s)
SHA_REMOTO=$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha256"])')
echo "POST de $MB MB por la tailnet: $((FIN - INICIO)) s"
[ "$SHA_LOCAL" = "$SHA_REMOTO" ] && echo "Integridad: sha256 coincide" || { echo "Integridad: NO coincide"; exit 1; }

echo "== Aislamiento por etiqueta (la ACL de la tailnet, no el firewall del Mac) =="
# Solo 8001 y 6379 son pruebas de ACL: son los únicos puertos que `tailscale serve` publica; en 22 y 5432
# nada escucha en la tailnet, así que ahí el bloqueo no distingue ACL de servicio ausente.
# `tailscale nc` con stdin vacío: conexión permitida -> sale al instante (0); bloqueada -> se agota (124).
alcanza() { # contenedor puerto -> imprime "permitido" o "BLOQUEADO"
    if docker exec "$1" sh -c "timeout 8 tailscale --socket=/tmp/tailscaled.sock nc $MAC $2 </dev/null >/dev/null 2>&1"; then
        echo permitido
    else
        echo BLOQUEADO
    fi
}
printf 'cloud    -> mac:6379 (esperado: permitido) : %s\n' "$(alcanza ts-cloud 6379)"
printf 'cloud    -> mac:8001 (esperado: BLOQUEADO) : %s\n' "$(alcanza ts-cloud 8001)"
printf 'cloud    -> mac:22   (esperado: BLOQUEADO) : %s\n' "$(alcanza ts-cloud 22)"
printf 'cloud    -> mac:5432 (esperado: BLOQUEADO) : %s\n' "$(alcanza ts-cloud 5432)"
printf 'frontend -> mac:8001 (esperado: permitido) : %s\n' "$(alcanza ts-frontend 8001)"
printf 'frontend -> mac:6379 (esperado: BLOQUEADO) : %s\n' "$(alcanza ts-frontend 6379)"
printf 'frontend -> mac:22   (esperado: BLOQUEADO) : %s\n' "$(alcanza ts-frontend 22)"
echo "Listo."
