#!/bin/sh
# Docker Compose con la contraseña de PostgreSQL de `.secrets/postgres_password.txt` (fuente única, sin copia en
# ningún `.env`). Uso: sh scripts/compose.sh -f docker-compose.yml -f docker-compose.nativo.yml up -d
set -eu
cd "$(dirname "$0")/.."
. scripts/lib_compose.sh
compose "$@"
