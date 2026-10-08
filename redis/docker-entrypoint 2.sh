#!/bin/sh
# Escribe certificados y ACL en memoria (tmpfs, permisos 600) y arranca Redis.
# Variables: REDIS_TLS_CA_B64, REDIS_TLS_CERT_B64, REDIS_TLS_KEY_B64 (PEM en
# base64) y REDIS_PASSWORD (>= 32 bytes). Nunca se imprimen.
set -eu

DIR=${REDIS_TLS_DIR:-/dev/shm/redis-tls}
for v in REDIS_TLS_CA_B64 REDIS_TLS_CERT_B64 REDIS_TLS_KEY_B64 REDIS_PASSWORD; do
    eval "valor=\${$v:-}"
    [ -n "$valor" ] || { echo "Falta la variable $v" >&2; exit 1; }
done
[ "${#REDIS_PASSWORD}" -ge 32 ] || { echo "REDIS_PASSWORD debe tener al menos 32 caracteres" >&2; exit 1; }

umask 077
mkdir -p "$DIR"
printf '%s' "$REDIS_TLS_CA_B64" | base64 -d > "$DIR/ca.crt"
printf '%s' "$REDIS_TLS_CERT_B64" | base64 -d > "$DIR/server.crt"
printf '%s' "$REDIS_TLS_KEY_B64" | base64 -d > "$DIR/server.key"

HASH=$(printf '%s' "$REDIS_PASSWORD" | sha256sum | cut -d' ' -f1)
# Solo los streams de shared/config.py (fog:*, cloud:*) y las claves del
# limitador de login de Fog (auth:*), y solo los comandos que usan Fog y Cloud.
cat > "$DIR/users.acl" <<ACL
user default off
user sabre on #$HASH ~fog:* ~cloud:* ~auth:* -@all +ping +hello +client|setinfo +client|setname +xadd +xread +xreadgroup +xack +xgroup +xautoclaim +xlen +xtrim +expire +ttl +incr +incrby +set +del
ACL
chmod 600 "$DIR"/*

unset REDIS_TLS_CA_B64 REDIS_TLS_CERT_B64 REDIS_TLS_KEY_B64 REDIS_PASSWORD
exec redis-server /etc/redis/redis.conf
