"""New192FeatureExtractor — implementación de FeatureExtractorPort para los
modelos de 192 features (bloque biomecánico Fase B incluido).

Reproduce el camino de entrenamiento:
  1. features crudas de dataset/05_extract_features.py (`extract_person_features`
     + corrección de velocidad relativa del CM de `process_clip` + interpolación
     de saltos anómalos), y
  2. el preprocesamiento de dataset/lstm_6class/dataset.py (estandarización con
     feature_stats.npz y recorte a ±kσ).

El recorte y la ablación NO están fijos aquí: los define el
PreprocessingProfile de la versión de modelo (ver preprocessing_profile.py).
Viven en este adaptador y no en application/ ni en Cloud porque están
atadas 1:1 al checkpoint con el que se generaron las estadísticas (ver
PLAN_ARQUITECTURA_DDD.md sección 2.1, "Límite ML").
"""

from __future__ import annotations

import numpy as np

from fog.domain.models import ExtractedFeatures, PersonPose, TrackedSequence, WeaponSide
from fog.infrastructure.features.preprocessing_profile import PreprocessingProfile, clamp_and_ablate
from fog.ports.feature_extractor import FeatureExtractorPort
from shared.feature_extractor import (
    FEAT_VEL,
    TOTAL_FEATURES,
    apply_relative_cm_velocity,
    extract_person_features,
    interpolate_sequence,
)


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
        profile: PreprocessingProfile,
    ):
        """
        Args:
            mean, std: (192,) — del feature_stats.npz del modelo, calculadas
                       solo sobre el split de train.
            profile: recorte y ablación de la versión de modelo.

        Raises:
            ValueError: si mean/std no tienen shape (192,).
        """
        if mean.shape != (TOTAL_FEATURES,) or std.shape != (TOTAL_FEATURES,):
            raise ValueError(
                f"mean/std deben tener shape ({TOTAL_FEATURES},), "
                f"recibido mean={mean.shape} std={std.shape}"
            )
        self._mean = mean.astype(np.float32)
        self._std = std.astype(np.float32)
        self._profile = profile

    def extract_raw(
        self,
        tracked: TrackedSequence,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
    ) -> tuple[np.ndarray, int]:
        """Features crudas (T, 192), equivalentes a las que guarda 05_extract_features.py.

        Args:
            tracked: secuencia trackeada con IDs A/B ya resueltos.
            weapon_side_a: brazo armado de A.
            weapon_side_b: brazo armado de B.

        Returns:
            (secuencia cruda (T, 192) float32, frames corregidos por interpolación).
        """
        state_a = _PersonTrackState()
        state_b = _PersonTrackState()

        seq_a: list[np.ndarray] = []
        seq_b: list[np.ndarray] = []

        for tf in tracked.frames:
            # prev_cm_x de t-1: hay que leerlo antes de que step() lo actualice.
            prev_cm_x_a, prev_cm_x_b = state_a.prev_cm_x, state_b.prev_cm_x
            feat_a = state_a.step(tf.person_a, tracked.frame_w, tracked.frame_h, weapon_side_a)
            feat_b = state_b.step(tf.person_b, tracked.frame_w, tracked.frame_h, weapon_side_b)
            apply_relative_cm_velocity(
                feat_a, feat_b, tf.person_a.detected, tf.person_b.detected,
                prev_cm_x_a, prev_cm_x_b,
            )
            seq_a.append(feat_a)
            seq_b.append(feat_b)

        seq_a, corr_a = interpolate_sequence(seq_a)
        seq_b, corr_b = interpolate_sequence(seq_b)

        T = len(seq_a)
        raw = np.array(
            [np.concatenate([seq_a[t], seq_b[t]]) for t in range(T)], dtype=np.float32
        )
        return raw, corr_a + corr_b

    def normalize(self, raw: np.ndarray) -> np.ndarray:
        """Estandariza, recorta y ablaciona según el perfil (igual que
        `_standardize_and_clamp` de dataset/lstm_6class/dataset.py).

        Args:
            raw: (T, 192) features crudas; no se modifica.

        Returns:
            Secuencia (T, 192) float32 lista para el clasificador.
        """
        x = (raw - self._mean) / self._std
        return clamp_and_ablate(x, self._profile)

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

        raw, interpolated = self.extract_raw(tracked, weapon_side_a, weapon_side_b)
        sequence = self.normalize(raw)

        return ExtractedFeatures(sequence=sequence, stats={
            "error": None,
            "frames_processed": frames_processed,
            "frames_no_fencer": tracked.frames_no_fencer,
            "frames_single": tracked.frames_single,
            "frames_interpolated": interpolated,
            "lock_frame": tracked.lock_frame,
            "seq_shape": str(sequence.shape),
        })
