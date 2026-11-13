#!/bin/sh
# Copia al portapapeles el valor de una variable de Railway (DEPLOY09, Parte C2) sin mostrarlo.
# Imprime solo la huella (sha256 truncado a 8 caracteres) para compararla después en el contenedor.
#
# Uso, desde backend/:
#   sh scripts/copiar_secreto.sh <NOMBRE>   # pega en Railway, y al terminar:
#   sh scripts/copiar_secreto.sh --vaciar   # vacía el portapapeles
#
# Nombres: REDIS_URL, REDIS_TLS_CA_B64, REDIS_TLS_CERT_B64, REDIS_TLS_KEY_B64 (servicio cloud) y
# PROXY_SHARED_TOKEN (servicio frontend). TS_AUTHKEY no pasa por aquí: la crea el autor en Tailscale.
set -eu

cd "$(dirname "$0")/.."
S=${SECRETS_DIR:-.secrets}

huella() { shasum -a 256 | cut -c1-8; }

case "${1:-}" in
    --vaciar) pbcopy < /dev/null; echo "Portapapeles vaciado."; exit 0 ;;
    REDIS_URL)
        valor=$(printf 'rediss://cloud:%s@localhost:6379/0' "$(tr -d '\n' < "$S/redis/redis_password_cloud.txt")") ;;
    REDIS_TLS_CA_B64)   valor=$(base64 < "$S/redis/ca.crt" | tr -d '\n') ;;
    REDIS_TLS_CERT_B64) valor=$(base64 < "$S/redis/cloud.crt" | tr -d '\n') ;;
    REDIS_TLS_KEY_B64)  valor=$(base64 < "$S/redis/cloud.key" | tr -d '\n') ;;
    PROXY_SHARED_TOKEN) valor=$(tr -d '\n' < "$S/proxy_token.txt") ;;
    *) echo "Nombre no válido: ${1:-}. Ver el encabezado del script." >&2; exit 2 ;;
esac
printf '%s' "$valor" | pbcopy
echo "$1 copiado: longitud=${#valor} huella=$(printf '%s' "$valor" | huella)"
