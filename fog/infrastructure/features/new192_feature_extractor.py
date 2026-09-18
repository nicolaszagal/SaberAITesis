"""New192FeatureExtractor — implementación de FeatureExtractorPort para el
pipeline lstm_4class (192 features, bloque biomecánico Fase B incluido,
estandarizado con feature_stats.npz, velocidades clampeadas a ±5σ y la
ablación diagnóstica de vel_elbow_angle).

La estandarización/clamping/ablación viven aquí, no en application/ ni en
Cloud, porque están atadas 1:1 al checkpoint con el que se generaron las
estadísticas (ver PLAN_ARQUITECTURA_DDD.md sección 2.1, "Límite ML").

Replica exactamente el preprocesamiento de dataset/lstm_4class/lstm_dataset.py
(estandarización, slices de clamping, ABLATE_INDICES=[95,191]) — verificado
por lectura directa de ese archivo.
"""

from __future__ import annotations

import numpy as np

from fog.domain.models import ExtractedFeatures, PersonPose, TrackedSequence, WeaponSide
from fog.ports.feature_extractor import FeatureExtractorPort
from shared.feature_extractor import FEAT_VEL, TOTAL_FEATURES, extract_person_features, interpolate_sequence

# Mismos slices que dataset/lstm_4class/lstm_dataset.py (verificado por lectura).
_VEL_A_SLICE = slice(51, 85)
_VEL_B_SLICE = slice(147, 181)
_CMVEL_A_SLICE = slice(91, 94)
_CMVEL_B_SLICE = slice(187, 190)
_VEL_CLAMP = 5.0

# Ablación diagnóstica de Fase B (dataset/lstm_4class/lstm_dataset.py,
# ABLATE_INDICES). El checkpoint desplegado se entrenó y evaluó con estas
# columnas en 0 — replicarlo es necesario para que la accuracy en
# producción coincida con la documentada (53.8% / 66.3% con máscara Favero).
DEFAULT_ABLATE_INDICES = [95, 191]


class _PersonTrackState:
    """Estado de un tirador que `extract_person_features` necesita del
    frame anterior para calcular velocidades/deltas. Encapsula la tupla de
    6 valores previos que antes se repetía en dos variables paralelas
    (una por tirador) en `_extract_sequence`."""

    def __init__(self):
        self.prev_rel = np.zeros(FEAT_VEL, dtype=np.float32)
        self.prev_dist_ankles = 0.0
        self.prev_weapon_ext = 0.0
        self.prev_cm_x = 0.0
        self.prev_cm_y = 0.0
        self.prev_elbow_angle = 0.0

    def step(self, person: PersonPose, frame_w: int, frame_h: int, weapon_side: WeaponSide) -> np.ndarray:
        (
            feat, self.prev_rel, self.prev_dist_ankles, self.prev_weapon_ext,
            self.prev_cm_x, self.prev_cm_y, self.prev_elbow_angle,
        ) = extract_person_features(
            person.detected, person.keypoints_xy, person.keypoints_conf, person.box_xyxy,
            frame_w, frame_h, self.prev_rel, self.prev_dist_ankles, self.prev_weapon_ext,
            weapon_side.value, self.prev_cm_x, self.prev_cm_y, self.prev_elbow_angle,
        )
        return feat


class New192FeatureExtractor(FeatureExtractorPort):
    def __init__(
        self,
        mean: np.ndarray,
        std: np.ndarray,
        ablate_indices: list[int] | None = None,
    ):
        """
        Args:
            mean, std: (192,) — de dataset/lstm_4class/feature_stats.npz,
                       calculadas solo sobre el split de train.
            ablate_indices: columnas a anular tras estandarizar. None usa
                       DEFAULT_ABLATE_INDICES; [] desactiva la ablación
                       (cambiaría la accuracy respecto a lo documentado).
        """
        if mean.shape != (TOTAL_FEATURES,) or std.shape != (TOTAL_FEATURES,):
            raise ValueError(
                f"mean/std deben tener shape ({TOTAL_FEATURES},), "
                f"recibido mean={mean.shape} std={std.shape}"
            )
        self._mean = mean.astype(np.float32)
        self._std = std.astype(np.float32)
        self._ablate_indices = (
            DEFAULT_ABLATE_INDICES if ablate_indices is None else list(ablate_indices)
        )

    def extract(
        self,
        tracked: TrackedSequence,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
        min_frames: int = 3,
    ) -> ExtractedFeatures:
        if not tracked.locked:
            return ExtractedFeatures(sequence=None, stats={"error": "tracking no pudo asignar IDs A/B"})

        frames_processed = len(tracked.frames)
        if frames_processed < min_frames:
            return ExtractedFeatures(sequence=None, stats={
                "error": f"secuencia muy corta ({frames_processed} frames, mínimo {min_frames})",
                "frames_processed": frames_processed,
            })

        state_a = _PersonTrackState()
        state_b = _PersonTrackState()

        seq_a: list[np.ndarray] = []
        seq_b: list[np.ndarray] = []

        for tf in tracked.frames:
            seq_a.append(state_a.step(tf.person_a, tracked.frame_w, tracked.frame_h, weapon_side_a))
            seq_b.append(state_b.step(tf.person_b, tracked.frame_w, tracked.frame_h, weapon_side_b))

        seq_a, corr_a = interpolate_sequence(seq_a)
        seq_b, corr_b = interpolate_sequence(seq_b)

        T = len(seq_a)
        sequence = np.array(
            [np.concatenate([seq_a[t], seq_b[t]]) for t in range(T)], dtype=np.float32
        )  # (T, 192) crudo

        sequence = (sequence - self._mean) / self._std
        sequence[:, _VEL_A_SLICE] = np.clip(sequence[:, _VEL_A_SLICE], -_VEL_CLAMP, _VEL_CLAMP)
        sequence[:, _VEL_B_SLICE] = np.clip(sequence[:, _VEL_B_SLICE], -_VEL_CLAMP, _VEL_CLAMP)
        sequence[:, _CMVEL_A_SLICE] = np.clip(sequence[:, _CMVEL_A_SLICE], -_VEL_CLAMP, _VEL_CLAMP)
        sequence[:, _CMVEL_B_SLICE] = np.clip(sequence[:, _CMVEL_B_SLICE], -_VEL_CLAMP, _VEL_CLAMP)
        if self._ablate_indices:
            sequence[:, self._ablate_indices] = 0.0

        return ExtractedFeatures(sequence=sequence, stats={
            "error": None,
            "frames_processed": frames_processed,
            "frames_no_fencer": tracked.frames_no_fencer,
            "frames_single": tracked.frames_single,
            "frames_interpolated": corr_a + corr_b,
            "lock_frame": tracked.lock_frame,
            "seq_shape": str(sequence.shape),
        })
