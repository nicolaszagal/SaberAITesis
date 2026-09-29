"""La etiqueta de v_muestras_confirmadas es siempre `veredicto.clase_final`.

`clase_final` pasa a ser obligatoria con `mantener` y `cambiar` (y sigue
prohibida con `anular`): "mantener"/"cambiar" describen la relación con la
decisión original del árbitro en pista y `clase_final` es siempre la
decisión final declarada. La vista deja de derivar la etiqueta de la clase
sugerida (`CASE decision ...`) y usa `v.clase_final`, excluyendo `anular`.

0001_esquema_sabre.sql ya trae la vista con esta definición (se mantiene
igual que docs_claude/sabre_ai_schema.sql); esta migración la aplica a bases
que corrieron 0001 antes del cambio. La vista no tiene dependientes, así que
se recrea con DROP + CREATE (CREATE OR REPLACE exige el mismo tipo de columna).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_FROM_WHERE = """
FROM sabre.revision_var r
JOIN sabre.veredicto v      ON v.revision_id = r.id
JOIN sabre.clasificacion c  ON c.id = r.clasificacion_id
JOIN sabre.modelo_version m ON m.id = c.modelo_version_id
WHERE v.decision <> 'anular' AND c.disponible
"""

_VISTA_NUEVA = f"""
CREATE VIEW sabre.v_muestras_confirmadas AS
SELECT r.id AS revision_id,
       c.keypoints_uri, c.keypoints_sha256,
       c.clase AS clase_sugerida,
       v.clase_final AS etiqueta,
       v.decision, m.nombre AS modelo, v.registrado_en
{_FROM_WHERE}"""

_VISTA_ANTERIOR = f"""
CREATE VIEW sabre.v_muestras_confirmadas AS
SELECT r.id AS revision_id,
       c.keypoints_uri, c.keypoints_sha256,
       c.clase AS clase_sugerida,
       CASE v.decision WHEN 'mantener' THEN c.clase
                       WHEN 'cambiar'  THEN v.clase_final END AS etiqueta,
       v.decision, m.nombre AS modelo, v.registrado_en
{_FROM_WHERE}"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS sabre.v_muestras_confirmadas")
    op.execute(_VISTA_NUEVA)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS sabre.v_muestras_confirmadas")
    op.execute(_VISTA_ANTERIOR)
