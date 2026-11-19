"""Elimina `sabre.decision_pista` (SCOPE01, 19/11/2026).

La tabla la creó 0007 (EDGE02) para la decisión en pista de los tocados capturados por Edge. El recorte de
alcance (sin Favero ni captura automática) la deja sin uso, y esta migración la elimina **solo si está vacía**:
si tiene filas aborta sin cambiar nada (no se pierden etiquetas). El trabajo vive en la rama
`future/edge-favero` (ver `docs/FUTURO_EDGE_FAVERO.md` allí).

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE n bigint;
        BEGIN
            IF to_regclass('sabre.decision_pista') IS NOT NULL THEN
                EXECUTE 'SELECT count(*) FROM sabre.decision_pista' INTO n;
                IF n > 0 THEN
                    RAISE EXCEPTION 'decision_pista tiene % fila(s): no se elimina (SCOPE01)', n;
                END IF;
                DROP TABLE sabre.decision_pista;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    # Se recrea vacía (la migración 0007 sabe crearla); los datos no se recuperan.
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
