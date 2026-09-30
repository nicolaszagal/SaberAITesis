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


# Taxonomía única de la API y del dominio (D-06): los nombres del modelo. La
# traducción a los del esquema vive solo en los adaptadores de persistencia.
CLASES_MODELO = (
    "AttackA", "AttackB", "ContrattackA", "ContrattackB", "RiposteA", "RiposteB",
)


class WeaponSide(str, Enum):
    RIGHT = "right"
    LEFT = "left"


_BRAZO_POR_LADO = {WeaponSide.RIGHT: "diestro", WeaponSide.LEFT: "zurdo"}


def brazo_de(side: WeaponSide) -> str:
    """Traduce el lado del arma de la API al dominio `brazo` del esquema.

    Args:
        side: lado del arma (`right` o `left`).

    Returns:
        `diestro` para `right`, `zurdo` para `left`.
    """
    return _BRAZO_POR_LADO[side]


def lado_de_brazo(brazo: str) -> WeaponSide:
    """Inversa de `brazo_de`.

    Args:
        brazo: valor del dominio `brazo` (`diestro` o `zurdo`).

    Returns:
        `WeaponSide.RIGHT` para `diestro`, `WeaponSide.LEFT` para `zurdo`.

    Raises:
        ValueError: si `brazo` no es un valor del dominio.
    """
    for side, valor in _BRAZO_POR_LADO.items():
        if valor == brazo:
            return side
    raise ValueError(f"brazo desconocido: {brazo!r}")


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


@dataclass(frozen=True)
class InstantesLuz:
    """Instante (ms desde el inicio del clip) de cada luz Favero simulada.

    La luz encendida se deduce de que exista su instante (`None` = apagada).
    El modelo solo usa si cada luz está encendida (`luz`): los instantes no
    entran a las features, a la ventana ni a la entrada del modelo.
    """

    t_luz_a_ms: int | None
    t_luz_b_ms: int | None

    def __post_init__(self) -> None:
        if self.t_luz_a_ms is None and self.t_luz_b_ms is None:
            raise ValueError("se requiere al menos una luz (t_luz_a_ms o t_luz_b_ms)")

    @property
    def luz(self) -> "LuzSignal":
        return LuzSignal(
            has_luz_a=self.t_luz_a_ms is not None, has_luz_b=self.t_luz_b_ms is not None
        )

    @property
    def t_tocado_ms(self) -> int:
        """El menor de los instantes encendidos (calculado en el servidor)."""
        return min(t for t in (self.t_luz_a_ms, self.t_luz_b_ms) if t is not None)


class MotivoNoDisponible(str, Enum):
    """Motivos de `clasificacion.motivo_no_disp` (docs_claude/sabre_ai_schema.sql).
    Fog solo produce POSE_INCOMPLETA: es el único caso que FeatureExtractorPort
    detecta (sin lock A/B, o secuencia bajo min_frames — ver
    New192FeatureExtractor.extract). CONFIANZA_BAJA (umbral no documentado)
    y CLASE_FUERA_MVP son responsabilidad de Cloud; TIMEOUT lo usa Fog
    cuando Cloud no responde (ver ClipUploadResponse.timed_out); SIN_SENAL_FAVERO
    no aplica en v1 (Fog no bloquea el procesamiento por falta de luz, ver
    LuzSignal.none())."""

    POSE_INCOMPLETA = "pose_incompleta"
    CONFIANZA_BAJA = "confianza_baja"
    CLASE_FUERA_MVP = "clase_fuera_mvp"
    TIMEOUT = "timeout"
    SIN_SENAL_FAVERO = "sin_senal_favero"
    MENSAJE_INVALIDO = "mensaje_invalido"  # lo produce Cloud (DEF-09)


@dataclass(frozen=True)
class UnavailableResult:
    """Resultado "no disponible" (RF-13, CU-06 flujo alterno 1a): Fog no
    pudo extraer features válidas y no llega a publicar en Redis. A
    diferencia de VerdictView, nunca sale de Fog vía Redis — se entrega
    directo a la sesión (WebSocket o respuesta síncrona de
    POST /matches/{match_id}/clip). Se identifica por `revision_id`: un
    combate admite N revisiones."""

    match_id: str
    revision_id: str
    motivo: MotivoNoDisponible

    def to_ws_message(self) -> dict:
        return {
            "type": "no_disponible",
            "match_id": self.match_id,
            "revision_id": self.revision_id,
            "motivo": self.motivo.value,
        }


@dataclass
class VerdictView:
    """Veredicto tal como lo recibe Fog desde Cloud, listo para reenviar al
    front por WebSocket. No reusa el `Verdict` de cloud/domain (bounded
    contexts separados) — solo modela los campos que Fog necesita reenviar."""

    match_id: str
    revision_id: str
    fencer: str
    action: str
    confidence: float
    # Campos de auditoría (RF-22, RNF-04) que Cloud publica junto al veredicto;
    # opcionales porque el front no los usa y no siempre están presentes.
    probs: dict[str, float] | None = None
    latencia_inferencia_ms: int | None = None
    modelo: str | None = None

    def to_ws_message(self) -> dict:
        return {
            "type": "veredicto",
            "match_id": self.match_id,
            "revision_id": self.revision_id,
            "fencer": self.fencer,
            "action": self.action,
            "confidence": self.confidence,
        }


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
