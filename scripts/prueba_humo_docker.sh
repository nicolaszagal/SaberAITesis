#!/bin/sh
# Prueba de humo de la Validación 1 en Docker (un clip por clase hasta el veredicto).
# Usa el proyecto "sabre-humo": base, Redis y datos propios; no toca la validación.
# Ejecutar desde backend/:  sh scripts/prueba_humo_docker.sh
set -e

# Fog exige autenticación (DEPLOY05): credenciales descartables, solo para esta
# corrida (no se guardan). Requiere el venv de backend/ (argon2-cffi).
AUTH_USER=humo
SABRE_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))")
AUTH_PASSWORD_HASH=$(printf %s "$SABRE_PASSWORD" | python3 -c "import sys; from argon2 import PasswordHasher; print(PasswordHasher().hash(sys.stdin.read()))")
AUTH_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
export AUTH_USER SABRE_PASSWORD AUTH_PASSWORD_HASH AUTH_JWT_SECRET

C="docker compose -p sabre-humo --env-file humo.env -f docker-compose.yml -f docker-compose.humo.yml"

$C up -d --build --wait fog
SESION=$($C exec -T fog python scripts/crear_sesion_validacion.py --evento "Humo" \
    --fecha 2026-09-29 --arbitro "Arbitro Humo" --operador "Operador Humo")
echo "$SESION"
EVENTO=$(echo "$SESION" | sed -n 's/^evento_id: \([^ ]*\).*/\1/p')
ARBITRO=$(echo "$SESION" | sed -n 's/^arbitro_id: \([^ ]*\).*/\1/p')

$C exec -T -e SABRE_PASSWORD fog python scripts/prueba_humo.py --evento "$EVENTO" --arbitro "$ARBITRO" \
    --redis-url redis://redis:6379/0 --salida /data/evidencia/humo.json
