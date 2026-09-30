"""Datos iniciales de la Validación 1 (V01): 2 eventos y 2 usuarios.

Precarga lo que la pantalla "Configurar combate" necesita, sin vistas ni
scripts manuales y con el mismo resultado en modo Docker y en modo nativo:

- Evento "Evento de prueba" (tipo `formativo`), para ensayar.
- Evento "Validación 1" (tipo `piloto`), para la sesión real.
- Usuario "Árbitro de prueba" (rol `arbitro`).
- Usuario "Operador de prueba" (rol `operador`).

Los dos eventos existen para que los ensayos no se mezclen con la evidencia del
piloto. Es idempotente: inserta solo lo que no existe por nombre y no toca las
filas existentes. `evento.fecha` es NOT NULL y no hay una fecha documentada: se
usa la fecha en que corre la migración. El downgrade no borra nada, porque
esas filas pueden tener combates asociados.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

EVENTOS = (
    ("Evento de prueba", "formativo"),
    ("Validación 1", "piloto"),
)
USUARIOS = (
    ("Árbitro de prueba", "arbitro"),
    ("Operador de prueba", "operador"),
)


def upgrade() -> None:
    for nombre, tipo in EVENTOS:
        op.execute(
            f"INSERT INTO sabre.evento (nombre, fecha, tipo) "
            f"SELECT '{nombre}', CURRENT_DATE, '{tipo}' "
            f"WHERE NOT EXISTS (SELECT 1 FROM sabre.evento WHERE nombre = '{nombre}')"
        )
    for nombre, rol in USUARIOS:
        op.execute(
            f"INSERT INTO sabre.usuario (nombre, rol) "
            f"SELECT '{nombre}', '{rol}' "
            f"WHERE NOT EXISTS (SELECT 1 FROM sabre.usuario WHERE nombre = '{nombre}')"
        )


def downgrade() -> None:
    """No borra: los datos iniciales pueden tener combates asociados."""
