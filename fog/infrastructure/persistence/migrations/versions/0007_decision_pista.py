"""Agrega `sabre.decision_pista` (EDGE02): decisión en pista de cada tocado.

Tabla de solo adición con la clase que canta el árbitro (o "anulado"), registrada
sin mostrar la sugerencia (D-04). 0001_esquema_sabre.sql ya la trae (igual que
docs_claude/sabre_ai_schema.sql); esta migración la agrega a bases que corrieron
0001 antes del cambio, por eso usa IF NOT EXISTS.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sabre.decision_pista (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tocado_id      UUID NOT NULL REFERENCES sabre.tocado(id),
            clase          sabre.clase_tact,
            anulado        BOOLEAN NOT NULL DEFAULT FALSE,
            registrado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
            registrado_por UUID REFERENCES sabre.usuario(id),
            CHECK (anulado = (clase IS NULL))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_decision_pista_tocado "
        "ON sabre.decision_pista(tocado_id, registrado_en DESC)"
    )
    op.execute("DROP TRIGGER IF EXISTS tg_decision_pista_inmutable ON sabre.decision_pista")
    op.execute(
        "CREATE TRIGGER tg_decision_pista_inmutable BEFORE UPDATE OR DELETE ON sabre.decision_pista "
        "FOR EACH ROW EXECUTE FUNCTION sabre.fn_bloquear_cambios()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sabre.decision_pista")
