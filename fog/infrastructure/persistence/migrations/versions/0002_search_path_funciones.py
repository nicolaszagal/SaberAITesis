"""Fija search_path en las funciones de sabre (mitiga search_path hijacking).

fn_auditoria_hash(), fn_bloquear_cambios() y fn_verificar_auditoria()
referencian tablas de `sabre` sin calificar; sin un search_path fijo por
función, una sesión con un search_path distinto al esperado (p. ej. un rol
que puede crear objetos en un esquema anterior en su propio search_path)
podría hacer que la función resuelva esos nombres contra tablas ajenas.
0001_esquema_sabre.sql ya crea las funciones con
`SET search_path = sabre, pg_temp`; esta migración lo agrega a bases que
corrieron 0001 antes de ese cambio.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

FUNCIONES = (
    "sabre.fn_auditoria_hash()",
    "sabre.fn_bloquear_cambios()",
    "sabre.fn_verificar_auditoria()",
)


def upgrade() -> None:
    for funcion in FUNCIONES:
        op.execute(f"ALTER FUNCTION {funcion} SET search_path = sabre, pg_temp")


def downgrade() -> None:
    for funcion in FUNCIONES:
        op.execute(f"ALTER FUNCTION {funcion} RESET search_path")
