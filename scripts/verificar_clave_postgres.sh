#!/bin/sh
# Comprueba, sin imprimirlas, qué contraseñas acepta el usuario `sabre` de PostgreSQL: la de
# `.secrets/postgres_password.txt` debe ser aceptada y la antigua de ejemplo (`sabre_local`) rechazada.
# Uso: sh scripts/verificar_clave_postgres.sh [puerto]    (por defecto POSTGRES_HOST_PORT o 5436)
# Código de salida 0 solo si la de .secrets funciona y la vieja se rechaza. Si la de .secrets es rechazada,
# la rotación de SEC01 no se aplicó en el volumen: `ALTER ROLE sabre PASSWORD '<la de .secrets>'`.
set -eu
cd "$(dirname "$0")/.."
PUERTO=${1:-${POSTGRES_HOST_PORT:-5436}}
BASE=${POSTGRES_DB_NAME:-sabre}
PSQL=${PSQL:-psql}
ARCHIVO=${SECRETS_DIR:-.secrets}/postgres_password.txt
[ -s "$ARCHIVO" ] || { echo "falta $ARCHIVO" >&2; exit 1; }
probar() { PGPASSWORD="$1" PGCONNECT_TIMEOUT=5 "$PSQL" -h 127.0.0.1 -p "$PUERTO" -U sabre -d "$BASE" -tAc "select 1" >/dev/null 2>&1; }
estado=0
if probar "$(tr -d '\n\r' < "$ARCHIVO")"; then echo "contraseña de .secrets: ACEPTADA"; else echo "contraseña de .secrets: RECHAZADA"; estado=1; fi
if probar "sabre_local"; then echo "contraseña antigua (sabre_local): ACEPTADA (debe rechazarse)"; estado=1; else echo "contraseña antigua (sabre_local): rechazada"; fi
exit $estado
