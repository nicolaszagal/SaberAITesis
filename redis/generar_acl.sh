#!/bin/sh
# Genera el archivo ACL de Redis con un usuario por nodo (SEC02).
#
# Uso: REDIS_PASSWORD_FOG=... REDIS_PASSWORD_CLOUD=... sh generar_acl.sh <archivo.acl>
#
# Los permisos salen de los comandos que ejecuta el código (no se asume nada más):
#   fog   -> XADD fog:features (RedisFeaturePublisher), XREAD cloud:verdicts:*
#            (RedisVerdictSubscriber, solo lectura) y PING (sonda de /health).
#   cloud -> XGROUP CREATE, XREADGROUP, XACK y XAUTOCLAIM sobre fog:features
#            (RedisFeatureConsumer), XADD en fog:features:dead (dead-letter) y
#            en cloud:verdicts:*, y EXPIRE de cloud:verdicts:* (RedisVerdictPublisher).
# Cada permiso va en un selector con sus claves: ninguno borra, lee ni escribe
# fuera de lo suyo, y el usuario `default` queda apagado. Requiere Redis 7 o más.
set -eu

DESTINO=${1:?Uso: sh generar_acl.sh <archivo.acl>}
for v in REDIS_PASSWORD_FOG REDIS_PASSWORD_CLOUD; do
    eval "valor=\${$v:-}"
    [ "${#valor}" -ge 32 ] || { echo "$v debe tener al menos 32 caracteres" >&2; exit 1; }
done

hash_de() {
    if command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$1" | sha256sum | cut -d' ' -f1
    else
        printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1
    fi
}
HASH_FOG=$(hash_de "$REDIS_PASSWORD_FOG")
HASH_CLOUD=$(hash_de "$REDIS_PASSWORD_CLOUD")

BASE="resetkeys -@all +ping +hello +client|setinfo +client|setname"
umask 077
cat > "$DESTINO" <<ACL
user default off
user fog on #$HASH_FOG $BASE (+xadd ~fog:features) (+xread %R~cloud:verdicts:*)
user cloud on #$HASH_CLOUD $BASE (+xgroup|create +xreadgroup +xack +xautoclaim ~fog:features) (+xadd ~fog:features:dead ~cloud:verdicts:*) (+expire ~cloud:verdicts:*)
ACL
chmod 600 "$DESTINO"
