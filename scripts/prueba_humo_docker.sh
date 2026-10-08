#!/bin/sh
# Prueba de humo de la Validación 1 en Docker (un clip por clase hasta el veredicto).
# Usa el proyecto "sabre-humo": base, Redis y datos propios; no toca la validación.
# Ejecutar desde backend/:  sh scripts/prueba_humo_docker.sh
set -e

# Fog exige autenticación (DEPLOY05): credenciales descartables, solo para esta
# corrida (no se guardan). Usa el python del venv de backend/ (argon2-cffi).
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
AUTH_USER=humo
SABRE_PASSWORD=$($PY -c "import secrets; print(secrets.token_urlsafe(18))")
AUTH_PASSWORD_HASH=$(printf %s "$SABRE_PASSWORD" | $PY -c "import sys; from argon2 import PasswordHasher; print(PasswordHasher().hash(sys.stdin.read()))")
AUTH_JWT_SECRET=$($PY -c "import secrets; print(secrets.token_urlsafe(48))")
export AUTH_USER SABRE_PASSWORD AUTH_PASSWORD_HASH AUTH_JWT_SECRET

# `docker compose` (plugin) o `docker-compose` (binario suelto, p. ej. colima).
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
C="$DC -p sabre-humo --env-file humo.env -f docker-compose.yml -f docker-compose.humo.yml"

$C up -d --build --wait fog
SESION=$($C exec -T fog python scripts/crear_sesion_validacion.py --evento "Humo" \
    --fecha 2026-09-29 --arbitro "Arbitro Humo" --operador "Operador Humo")
echo "$SESION"
EVENTO=$(echo "$SESION" | sed -n 's/^evento_id: \([^ ]*\).*/\1/p')
ARBITRO=$(echo "$SESION" | sed -n 's/^arbitro_id: \([^ ]*\).*/\1/p')

$C exec -T -e SABRE_PASSWORD fog python scripts/prueba_humo.py --evento "$EVENTO" --arbitro "$ARBITRO" \
    --redis-url redis://redis:6379/0 --salida /data/evidencia/humo.json

# DEPLOY05: Fog corre sin root (UID 10001) y debe poder escribir en los volúmenes.
$C exec -T fog sh -c 'test "$(id -u)" != 0 \
    && test -s /data/evidencia/humo.json \
    && test "$(find /data/storage -type f | wc -l)" -gt 0' \
    && echo "permisos: Fog escribe en /data/storage y /data/evidencia sin ser root"
