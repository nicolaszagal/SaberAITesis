#!/bin/sh
# Prueba de humo de la Validación 1 en Docker (un clip por clase hasta el veredicto).
# Usa el proyecto "sabre-humo": base, Redis y datos propios; no toca la validación.
# Ejecutar desde backend/:  sh scripts/prueba_humo_docker.sh
set -e

C="docker compose -p sabre-humo --env-file humo.env -f docker-compose.yml -f docker-compose.humo.yml"

$C up -d --build --wait fog
SESION=$($C exec -T fog python scripts/crear_sesion_validacion.py --evento "Humo" \
    --fecha 2026-09-29 --arbitro "Arbitro Humo" --operador "Operador Humo")
echo "$SESION"
EVENTO=$(echo "$SESION" | sed -n 's/^evento_id: \([^ ]*\).*/\1/p')
ARBITRO=$(echo "$SESION" | sed -n 's/^arbitro_id: \([^ ]*\).*/\1/p')

$C exec -T fog python scripts/prueba_humo.py --evento "$EVENTO" --arbitro "$ARBITRO" \
    --redis-url redis://redis:6379/0 --salida /data/evidencia/humo.json
