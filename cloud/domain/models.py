"""
Entidades y value objects del dominio de Cloud.

Bounded context propio: no reusa tipos de fog/domain (ver
PLAN_ARQUITECTURA_DDD.md sección 2.2). `LuzSignal` está duplicado
intencionalmente respecto a fog/domain/models.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class ActionClass(str, Enum):
    ATTACK_A = "AttackA"
    ATTACK_B = "AttackB"
    RESPONSE_A = "ResponseA"
    RESPONSE_B = "ResponseB"


CLASSES: list[str] = [c.value for c in ActionClass]


@dataclass(frozen=True)
class LuzSignal:
    has_luz_a: bool
    has_luz_b: bool

    @staticmethod
    def none() -> "LuzSignal":
        return LuzSignal(has_luz_a=False, has_luz_b=False)


@dataclass
class FeatureSequence:
    """Features ya extraídas y estandarizadas por Fog, tal como llegan
    por el stream `fog:features`."""

    match_id: str
    sequence: np.ndarray  # (T, 192) float32
    luz: LuzSignal
    weapon_side_a: str
    weapon_side_b: str


@dataclass
class RawVerdict:
    """Salida cruda de ActionClassifierPort, antes de ArbitrationPolicyPort."""

    action_class: ActionClass
    confidence: float
    probs: dict[str, float] = field(default_factory=dict)  # softmax completo, por clase


class MotivoNoDisponible(str, Enum):
    """Motivos de `clasificacion.motivo_no_disp` (docs_claude/sabre_ai_schema.sql).
    Cloud produce MENSAJE_INVALIDO cuando una entrada de `fog:features` no
    respeta el contrato (campo obligatorio faltante, shape/dtype/tamaño de
    buffer inconsistentes — ver CONTRATO_API.md sección 5 y DEF-09). Los
    demás valores son responsabilidad de Fog (POSE_INCOMPLETA,
    SIN_SENAL_FAVERO, ver fog/domain/models.py) o de una etapa de Cloud
    todavía no implementada (CONFIANZA_BAJA, CLASE_FUERA_MVP, TIMEOUT)."""

    POSE_INCOMPLETA = "pose_incompleta"
    CONFIANZA_BAJA = "confianza_baja"
    CLASE_FUERA_MVP = "clase_fuera_mvp"
    TIMEOUT = "timeout"
    SIN_SENAL_FAVERO = "sin_senal_favero"
    MENSAJE_INVALIDO = "mensaje_invalido"


@dataclass(frozen=True)
class InvalidFeatureMessage:
    """Entrada de `fog:features` que RedisFeatureConsumer no pudo parsear
    (DEF-09). `match_id` es None si ni ese campo estaba presente/decodificable
    — en ese caso no hay dónde publicar el veredicto "no disponible"."""

    match_id: str | None
    motivo: MotivoNoDisponible
    detalle: str


@dataclass
class Verdict:
    """Veredicto final, después de aplicar ArbitrationPolicyPort. Es lo
    que se publica en `cloud:verdicts:{match_id}` para Fog.

    Dos formas, igual que `clasificacion` en sabre_ai_schema.sql:
    - disponible=True: `action_class`, `confidence`, `fencer`, `probs`,
      `latencia_inferencia_ms` y `modelo` van completos; `motivo_no_disp` es None.
    - disponible=False: solo `match_id` y `motivo_no_disp`; el resto queda None.
    """

    match_id: str
    disponible: bool
    action_class: ActionClass | None = None
    confidence: float | None = None
    fencer: str | None = None  # "ROJ" o "VER", ver shared.config.FENCER_COLOR
    probs: dict[str, float] | None = None  # softmax post filtro Favero, por clase
    latencia_inferencia_ms: int | None = None
    modelo: str | None = None  # shared.config.MODEL_VERSION_NAME
    motivo_no_disp: str | None = None  # uno de MotivoNoDisponible, si disponible=False
