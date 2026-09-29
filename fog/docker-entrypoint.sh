#!/bin/sh
# Aplica las migraciones pendientes de la base `sabre` antes de levantar la
# API (ver fog/infrastructure/persistence/migrations/). alembic.ini fija
# script_location de forma relativa a este WORKDIR (/app/backend).
set -e

alembic upgrade head

exec uvicorn fog.main:app --host 0.0.0.0 --port 8001
