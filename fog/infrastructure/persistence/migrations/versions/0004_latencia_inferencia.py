"""Agrega `clasificacion.latencia_inferencia_ms` (F-027, RNF-04).

Guarda el tiempo del clasificador en Cloud por clip, para auditar el
presupuesto de 50 ms desde la base. Es NULL en las clasificaciones no
disponibles (no hubo inferencia). `latencia_ms` sigue siendo la latencia de
la sugerencia completa medida por Fog.

0001_esquema_sabre.sql ya trae la columna (se mantiene igual que
docs_claude/sabre_ai_schema.sql); esta migración la agrega a bases que
corrieron 0001 antes del cambio, por eso usa IF NOT EXISTS. Las filas
anteriores quedan en NULL.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sabre.clasificacion ADD COLUMN IF NOT EXISTS "
        "latencia_inferencia_ms INT CHECK (latencia_inferencia_ms >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sabre.clasificacion DROP COLUMN IF EXISTS latencia_inferencia_ms"
    )
