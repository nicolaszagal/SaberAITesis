#!/bin/sh
# Escribe certificados y ACL en memoria (tmpfs, permisos 600) y arranca Redis.
# Variables: REDIS_TLS_CA_B64, REDIS_TLS_CERT_B64, REDIS_TLS_KEY_B64 (PEM en
# base64), REDIS_PASSWORD_FOG y REDIS_PASSWORD_CLOUD (>= 32 caracteres cada una,
# una por nodo). Nunca se imprimen.
set -eu

DIR=${REDIS_TLS_DIR:-/dev/shm/redis-tls}
for v in REDIS_TLS_CA_B64 REDIS_TLS_CERT_B64 REDIS_TLS_KEY_B64 REDIS_PASSWORD_FOG REDIS_PASSWORD_CLOUD; do
    eval "valor=\${$v:-}"
    [ -n "$valor" ] || { echo "Falta la variable $v" >&2; exit 1; }
done

umask 077
mkdir -p "$DIR"
printf '%s' "$REDIS_TLS_CA_B64" | base64 -d > "$DIR/ca.crt"
printf '%s' "$REDIS_TLS_CERT_B64" | base64 -d > "$DIR/server.crt"
printf '%s' "$REDIS_TLS_KEY_B64" | base64 -d > "$DIR/server.key"

# Un usuario por nodo, con sus claves y comandos (ver generar_acl.sh).
sh "${ACL_SCRIPT:-/usr/local/bin/sabre-redis-generar-acl.sh}" "$DIR/users.acl"
chmod 600 "$DIR"/*

unset REDIS_TLS_CA_B64 REDIS_TLS_CERT_B64 REDIS_TLS_KEY_B64 REDIS_PASSWORD_FOG REDIS_PASSWORD_CLOUD
exec redis-server /etc/redis/redis.conf
