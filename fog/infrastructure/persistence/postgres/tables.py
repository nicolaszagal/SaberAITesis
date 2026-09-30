"""Definiciones SQLAlchemy Core de las tablas de `sabre` que usan los
adaptadores de D02/D03.

Sin ORM ni autogenerate a propósito (mismo criterio que
migrations/env.py: el esquema vive en SQL, no en Python) — Core alcanza
para las consultas mínimas de cada puerto. Solo se listan las columnas que
los adaptadores leen o escriben, no el esquema completo de cada tabla.
Cada `Table` califica `schema="sabre"` explícitamente: el engine
(fog/infrastructure/persistence/database.py) ya no fija `search_path`
(migración 0002).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(schema="sabre")

evento = sa.Table(
    "evento",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("nombre", sa.Text, nullable=False),
    sa.Column("fecha", sa.Date, nullable=False),
    sa.Column("lugar", sa.Text),
    sa.Column("tipo", sa.Text, nullable=False),
)

usuario = sa.Table(
    "usuario",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("nombre", sa.Text, nullable=False),
    sa.Column("rol", sa.Text, nullable=False),
    sa.Column("activo", sa.Boolean, nullable=False),
    sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)

tirador = sa.Table(
    "tirador",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("alias", sa.Text, nullable=False),
    sa.Column("brazo_habitual", sa.Text, nullable=False),
    sa.Column("es_menor", sa.Boolean, nullable=False),
    sa.Column("consentimiento_firmado", sa.Boolean, nullable=False),
    sa.Column("consentimiento_fecha", sa.Date),
    sa.Column("firmante", sa.Text),
    sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)

combate = sa.Table(
    "combate",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("evento_id", UUID(as_uuid=True)),
    sa.Column("pista", sa.Text, nullable=False),
    sa.Column("fase", sa.Text),
    sa.Column("tirador_a_id", UUID(as_uuid=True), nullable=False),
    sa.Column("tirador_b_id", UUID(as_uuid=True), nullable=False),
    sa.Column("brazo_a", sa.Text, nullable=False),
    sa.Column("brazo_b", sa.Text, nullable=False),
    sa.Column("arbitro_id", UUID(as_uuid=True), nullable=False),
    sa.Column("configurado_por", UUID(as_uuid=True), nullable=False),
    sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)

clip = sa.Table(
    "clip",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("combate_id", UUID(as_uuid=True), nullable=False),
    sa.Column("origen", sa.Text, nullable=False),
    sa.Column("camara", sa.Text, nullable=False),
    sa.Column("uri", sa.Text, nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("fps", sa.Numeric(6, 2), nullable=False),
    sa.Column("ancho_px", sa.Integer, nullable=False),
    sa.Column("alto_px", sa.Integer, nullable=False),
    sa.Column("duracion_ms", sa.Integer, nullable=False),
    sa.Column("t0_utc", sa.TIMESTAMP(timezone=True)),
    sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)

tocado = sa.Table(
    "tocado",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("combate_id", UUID(as_uuid=True), nullable=False),
    sa.Column("fuente", sa.Text, nullable=False),
    sa.Column("luz_a", sa.Boolean, nullable=False),
    sa.Column("luz_b", sa.Boolean, nullable=False),
    sa.Column("t_tocado_utc", sa.TIMESTAMP(timezone=True)),
    sa.Column("t_tocado_ms", sa.Integer),
    sa.Column("t_luz_a_ms", sa.Integer),
    sa.Column("t_luz_b_ms", sa.Integer),
    sa.Column("registrado_por", UUID(as_uuid=True)),
    sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)

tocado_clip = sa.Table(
    "tocado_clip",
    metadata,
    sa.Column("tocado_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("clip_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("frame_tocado", sa.Integer, nullable=False),
)

modelo_version = sa.Table(
    "modelo_version",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("nombre", sa.Text, nullable=False),
    sa.Column("checkpoint_uri", sa.Text, nullable=False),
    sa.Column("checkpoint_sha256", sa.String(64), nullable=False),
    sa.Column("pose_modelo", sa.Text, nullable=False),
    sa.Column("num_features", sa.Integer, nullable=False),
    sa.Column("num_clases", sa.Integer, nullable=False),
    sa.Column("reglamento", sa.Text, nullable=False),
    sa.Column("f1_macro_test", sa.Numeric(5, 4)),
    sa.Column("kappa_piloto", sa.Numeric(5, 4)),
    sa.Column("padre_id", UUID(as_uuid=True)),
    sa.Column("activo", sa.Boolean, nullable=False),
    sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)

clasificacion = sa.Table(
    "clasificacion",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tocado_id", UUID(as_uuid=True), nullable=False),
    sa.Column("modelo_version_id", UUID(as_uuid=True), nullable=False),
    sa.Column("disponible", sa.Boolean, nullable=False),
    sa.Column("motivo_no_disp", sa.Text),
    sa.Column("clase", sa.Text),
    sa.Column("tirador", sa.String(1)),
    sa.Column("confianza", sa.Numeric(5, 4)),
    sa.Column("probabilidades", JSONB),
    sa.Column("keypoints_uri", sa.Text, nullable=False),
    sa.Column("keypoints_sha256", sa.String(64), nullable=False),
    sa.Column("features_uri", sa.Text),
    sa.Column("latencia_ms", sa.Integer),
    sa.Column("latencia_inferencia_ms", sa.Integer),
    sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)

revision_var = sa.Table(
    "revision_var",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tocado_id", UUID(as_uuid=True), nullable=False),
    sa.Column("aceptada", sa.Boolean, nullable=False),
    sa.Column("arbitro_id", UUID(as_uuid=True), nullable=False),
    sa.Column("clasificacion_id", UUID(as_uuid=True)),
    sa.Column("abierta_en", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("cerrada_en", sa.TIMESTAMP(timezone=True)),
)

veredicto = sa.Table(
    "veredicto",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("revision_id", UUID(as_uuid=True), nullable=False),
    sa.Column("decision", sa.Text, nullable=False),
    sa.Column("clase_final", sa.Text),
    sa.Column("arbitro_id", UUID(as_uuid=True), nullable=False),
    sa.Column("registrado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)

registro_auditoria = sa.Table(
    "registro_auditoria",
    metadata,
    sa.Column("seq", sa.BigInteger, primary_key=True),
    sa.Column("revision_id", UUID(as_uuid=True), nullable=False),
    sa.Column("snapshot", JSONB, nullable=False),
    sa.Column("hash_prev", sa.String(64)),
    sa.Column("hash", sa.String(64), nullable=False),
    sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False),
)
