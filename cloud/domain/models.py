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


@dataclass
class Verdict:
    """Veredicto final, después de aplicar ArbitrationPolicyPort. Es lo
    que se publica en `cloud:verdicts:{match_id}` para Fog."""

    match_id: str
    action_class: ActionClass
    confidence: float
    fencer: str  # "ROJ" o "VER", ver shared.config.FENCER_COLOR
