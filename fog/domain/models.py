"""
Entidades y value objects del dominio de Fog.

Bounded context propio: Fog no comparte tipos de dominio con Cloud (ver
PLAN_ARQUITECTURA_DDD.md sección 2.2). `LuzSignal` y `VerdictView` están
duplicados intencionalmente en cloud/domain/models.py — son la forma en que
cada servicio modela un concepto que cruza el límite del wire format, no
lógica de negocio compartida.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class WeaponSide(str, Enum):
    RIGHT = "right"
    LEFT = "left"


@dataclass(frozen=True)
class PersonPose:
    """Pose de una persona en un frame, ya en arrays planos (sin tipos de
    ninguna librería de CV) para que PoseEstimatorPort sea intercambiable."""

    keypoints_xy: np.ndarray    # (17, 2) float32 — coords absolutas en pixeles, 0 si no detectado
    keypoints_conf: np.ndarray  # (17,) float32
    box_xyxy: np.ndarray        # (4,) float32 — x1,y1,x2,y2 absolutos
    detected: bool               # False => no se asignó ningún box a esta persona en este frame

    @staticmethod
    def empty() -> "PersonPose":
        return PersonPose(
            keypoints_xy=np.zeros((17, 2), dtype=np.float32),
            keypoints_conf=np.zeros(17, dtype=np.float32),
            box_xyxy=np.zeros(4, dtype=np.float32),
            detected=False,
        )


@dataclass(frozen=True)
class TrackedFrame:
    """Resultado de detección+tracking de un frame, con IDs A/B ya resueltos."""

    person_a: PersonPose
    person_b: PersonPose


@dataclass
class TrackedSequence:
    """Salida de PoseTrackingSession.finish() (ver fog/ports/pose_estimator.py):
    pose+tracking acumulado frame a frame durante la sesión completa."""

    frames: list[TrackedFrame]
    frame_w: int
    frame_h: int
    locked: bool                  # False => no se pudo bloquear un par de IDs A/B
    lock_frame: int | None = None
    frames_no_fencer: int = 0
    frames_single: int = 0


@dataclass
class ExtractedFeatures:
    """Salida de FeatureExtractorPort.extract. `sequence` es None si la
    secuencia es inválida (ver stats['error'])."""

    sequence: np.ndarray | None  # (T, 192) float32, ya estandarizada/clampeada
    stats: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LuzSignal:
    """Señal de luz Favero a nivel de clip. Ver Fase 1 del plan: hoy llega
    por anotación manual en el dataset; en producción llegará vía RJ11
    (Edge, fuera de alcance de este backend) a través del endpoint
    POST /webrtc/{match_id}/luz."""

    has_luz_a: bool
    has_luz_b: bool

    @staticmethod
    def none() -> "LuzSignal":
        return LuzSignal(has_luz_a=False, has_luz_b=False)


@dataclass
class VerdictView:
    """Veredicto tal como lo recibe Fog desde Cloud, listo para reenviar al
    front por WebSocket. No reusa el `Verdict` de cloud/domain (bounded
    contexts separados) — solo modela los campos que Fog necesita reenviar."""

    match_id: str
    fencer: str
    action: str
    confidence: float


@dataclass
class Match:
    """Entidad agregada persistida por MatchRepositoryPort. No incluye
    buffers de frames, websockets ni eventos de sincronización — eso es
    estado de runtime que vive en infrastructure/webrtc (ver
    SessionRegistry), no en el dominio."""

    match_id: str
    weapon_side_a: WeaponSide
    weapon_side_b: WeaponSide
    luz: LuzSignal | None = None
    verdict: VerdictView | None = None
