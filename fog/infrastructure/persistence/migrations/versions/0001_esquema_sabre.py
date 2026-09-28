"""Esquema inicial `sabre`.

Ejecuta tal cual docs_claude/sabre_ai_schema.sql (copia en
migrations/sql/0001_esquema_sabre.sql): dominios, tablas, triggers,
funciones y vista. No se cambia ningún nombre ni restricción.

Revision ID: 0001
Revises:
"""

from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_ESQUEMA = Path(__file__).resolve().parent.parent / "sql" / "0001_esquema_sabre.sql"


def upgrade() -> None:
    # El script tiene muchas sentencias (y cuerpos $$ con ';'), así que se
    # envía por el protocolo simple de asyncpg, que sí admite varias
    # sentencias; el cursor de SQLAlchemy las prepara de a una y falla.
    driver_connection = op.get_bind().connection.driver_connection
    await_only(driver_connection.execute(SQL_ESQUEMA.read_text(encoding="utf-8")))


def downgrade() -> None:
    # pgcrypto quedó instalada dentro de `sabre`, así que cae con el esquema.
    op.execute("DROP SCHEMA IF EXISTS sabre CASCADE")
