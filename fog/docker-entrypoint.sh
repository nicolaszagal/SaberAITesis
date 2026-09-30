#!/bin/sh
# Arranque de Fog sin pasos manuales: migra la base, registra el modelo
# desplegado solo si no hay una versión activa (idempotente) y levanta la API.
# alembic.ini fija script_location de forma relativa a este WORKDIR (/app/backend).
set -e

alembic upgrade head
python scripts/registrar_modelo.py "$MODEL_RUN_ID" --solo-si-no-hay-activo

exec uvicorn fog.main:app --host 0.0.0.0 --port 8001
