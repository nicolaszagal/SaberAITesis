#!/bin/sh
# PKI propia para Redis con mTLS (DEPLOY07): CA (1 año), certificado de servidor
# y un certificado de cliente para Fog y otro para Cloud. Salida en
# .secrets/redis/ (ignorado por git, permisos 600).
#
# Uso, desde backend/:
#   sh scripts/generar_pki_redis.sh <host-publico> [<otro-nombre> ...]
# Cada nombre va como SAN del certificado de servidor (por ejemplo el dominio
# del TCP proxy de Railway y redis.railway.internal). Los clientes verifican
# la CA y el nombre.
set -eu

[ "$#" -ge 1 ] || { echo "Uso: sh scripts/generar_pki_redis.sh <host> [<host> ...]" >&2; exit 2; }
cd "$(dirname "$0")/.."
OUT=.secrets/redis
[ ! -e "$OUT/ca.crt" ] || { echo "$OUT ya existe: bórrelo a mano para regenerar (rotación)." >&2; exit 1; }
mkdir -p "$OUT"
umask 077
DIAS=365

SAN=""
for h in "$@"; do SAN="$SAN${SAN:+,}DNS:$h"; done

openssl req -x509 -newkey rsa:4096 -nodes -days $DIAS -subj "/CN=SABRE.AI Redis CA" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -keyout "$OUT/ca.key" -out "$OUT/ca.crt" 2>/dev/null

emitir() { # nombre CN EKU SAN
    openssl req -newkey rsa:3072 -nodes -subj "/CN=$2" -keyout "$OUT/$1.key" -out "$OUT/$1.csr" 2>/dev/null
    printf 'basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=%s\n%s' \
        "$3" "${4:+subjectAltName=$4}" > "$OUT/$1.ext"
    openssl x509 -req -in "$OUT/$1.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" -CAcreateserial \
        -days $DIAS -extfile "$OUT/$1.ext" -out "$OUT/$1.crt" 2>/dev/null
    rm -f "$OUT/$1.csr" "$OUT/$1.ext"
}
emitir server "$1" serverAuth "$SAN"
emitir fog sabre-fog clientAuth ""
emitir cloud sabre-cloud clientAuth ""
rm -f "$OUT/ca.srl"

# Contraseña aleatoria de 48 bytes para el usuario `sabre`.
openssl rand -base64 48 | tr -d '\n=+/' > "$OUT/redis_password.txt"
chmod 600 "$OUT"/*
echo "PKI generada en $OUT (CA válida $DIAS días). Nada de esto va a git."
