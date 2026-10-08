"""Errores del dominio de auditoría de Fog.

Los casos de uso los lanzan sin conocer HTTP; el router
(`infrastructure/api/routes.py`) los traduce a códigos de estado.
"""


class ErrorDeDominio(Exception):
    """Base de los errores de reglas de negocio del flujo auditable."""


class RecursoNoEncontrado(ErrorDeDominio):
    """Un combate, evento, usuario o revisión referenciado no existe."""


class VeredictoYaRegistrado(ErrorDeDominio):
    """La revisión ya tiene veredicto (RF-21: el registro es único y final)."""


class ClasificacionPendiente(ErrorDeDominio):
    """La revisión aún no tiene clasificación registrada; sin ella el
    registro de auditoría no podría guardar versión de modelo (RF-22)."""


class SinModeloActivo(ErrorDeDominio):
    """No hay una fila activa en `modelo_version` (se registra con
    scripts/registrar_modelo.py)."""


class VeredictoInvalido(ErrorDeDominio):
    """Combinación decision/clase_final que el esquema no admite."""


class CredencialesInvalidas(ErrorDeDominio):
    """Usuario o contraseña incorrectos (mensaje único, sin distinguir cuál)."""


class DemasiadosIntentos(ErrorDeDominio):
    """La IP superó los intentos de login permitidos y está bloqueada.

    Attributes:
        reintentar_en_s: segundos que faltan para que termine el bloqueo.
    """

    def __init__(self, reintentar_en_s: int):
        super().__init__("demasiados intentos")
        self.reintentar_en_s = reintentar_en_s


class TokenInvalido(ErrorDeDominio):
    """Token ausente, vencido, con firma alterada o mal formado."""
