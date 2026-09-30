"""Agrega `tocado.t_luz_a_ms` y `tocado.t_luz_b_ms` (V02, CU-03).

Guarda el instante de cada luz Favero simulada (la señal de V2 también traerá
uno por luz). La luz encendida se deduce de que exista su instante:
`luz_a` es verdadera si y solo si `t_luz_a_ms` no es NULL, y lo mismo con B.
Las filas existentes se completan con `t_tocado_ms` en cada luz encendida.

0001_esquema_sabre.sql ya trae las columnas y los CHECK (se mantiene igual que
docs_claude/sabre_ai_schema.sql); esta migración los agrega a bases que
corrieron 0001 antes del cambio, por eso usa IF NOT EXISTS. No cambia las
features, la ventana ni la entrada del modelo.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

LADOS = ("a", "b")


def upgrade() -> None:
    for lado in LADOS:
        op.execute(
            f"ALTER TABLE sabre.tocado ADD COLUMN IF NOT EXISTS "
            f"t_luz_{lado}_ms INT CHECK (t_luz_{lado}_ms >= 0)"
        )
        op.execute(
            f"UPDATE sabre.tocado SET t_luz_{lado}_ms = t_tocado_ms "
            f"WHERE luz_{lado} AND t_luz_{lado}_ms IS NULL"
        )
        op.execute(
            f"ALTER TABLE sabre.tocado DROP CONSTRAINT IF EXISTS ck_tocado_luz_{lado}_instante"
        )
        op.execute(
            f"ALTER TABLE sabre.tocado ADD CONSTRAINT ck_tocado_luz_{lado}_instante "
            f"CHECK (luz_{lado} = (t_luz_{lado}_ms IS NOT NULL))"
        )


def downgrade() -> None:
    for lado in LADOS:
        op.execute(
            f"ALTER TABLE sabre.tocado DROP CONSTRAINT IF EXISTS ck_tocado_luz_{lado}_instante"
        )
        op.execute(f"ALTER TABLE sabre.tocado DROP COLUMN IF EXISTS t_luz_{lado}_ms")
