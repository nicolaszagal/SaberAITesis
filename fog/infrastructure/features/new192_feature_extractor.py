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

from fog.domain.models import ExtractedFeatures, TrackedSequence, WeaponSide
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

        prev_rel_a = np.zeros(FEAT_VEL, dtype=np.float32)
        prev_rel_b = np.zeros(FEAT_VEL, dtype=np.float32)
        prev_dist_ankles_a = prev_dist_ankles_b = 0.0
        prev_weapon_ext_a = prev_weapon_ext_b = 0.0
        prev_cm_x_a = prev_cm_y_a = prev_elbow_angle_a = 0.0
        prev_cm_x_b = prev_cm_y_b = prev_elbow_angle_b = 0.0

        seq_a: list[np.ndarray] = []
        seq_b: list[np.ndarray] = []

        for tf in tracked.frames:
            feat_a, prev_rel_a, prev_dist_ankles_a, prev_weapon_ext_a, prev_cm_x_a, prev_cm_y_a, prev_elbow_angle_a = (
                extract_person_features(
                    tf.person_a.detected, tf.person_a.keypoints_xy, tf.person_a.keypoints_conf,
                    tf.person_a.box_xyxy, tracked.frame_w, tracked.frame_h,
                    prev_rel_a, prev_dist_ankles_a, prev_weapon_ext_a, weapon_side_a.value,
                    prev_cm_x_a, prev_cm_y_a, prev_elbow_angle_a,
                )
            )
            feat_b, prev_rel_b, prev_dist_ankles_b, prev_weapon_ext_b, prev_cm_x_b, prev_cm_y_b, prev_elbow_angle_b = (
                extract_person_features(
                    tf.person_b.detected, tf.person_b.keypoints_xy, tf.person_b.keypoints_conf,
                    tf.person_b.box_xyxy, tracked.frame_w, tracked.frame_h,
                    prev_rel_b, prev_dist_ankles_b, prev_weapon_ext_b, weapon_side_b.value,
                    prev_cm_x_b, prev_cm_y_b, prev_elbow_angle_b,
                )
            )
            seq_a.append(feat_a)
            seq_b.append(feat_b)

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
