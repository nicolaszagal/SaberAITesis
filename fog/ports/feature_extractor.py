"""FeatureExtractorPort — cómputo biomecánico a partir de una secuencia
trackeada. Puerto independiente de ActionClassifierPort (decisión
explícita de Nicolas, ver PLAN_ARQUITECTURA_DDD.md sección 1): el historial
del proyecto (182→192 features, ablación Fase B) muestra que la
ingeniería de features evoluciona por separado de la arquitectura del
modelo, así que ambos deben poder cambiar de forma independiente.

Nota: aunque el puerto es independiente, una implementación concreta de
FeatureExtractorPort solo es válida para el/los checkpoint(s) entrenados
con su mismo esquema de columnas y estadísticas de normalización — por
eso la estandarización vive en el adaptador (infrastructure/features/),
no en application/.
"""

from abc import ABC, abstractmethod

from fog.domain.models import ExtractedFeatures, TrackedSequence, WeaponSide


class FeatureExtractorPort(ABC):
    @abstractmethod
    def extract(
        self,
        tracked: TrackedSequence,
        weapon_side_a: WeaponSide,
        weapon_side_b: WeaponSide,
        min_frames: int = 3,
    ) -> ExtractedFeatures:
        """
        Devuelve ExtractedFeatures con `sequence=None` y `stats["error"]`
        seteado si la secuencia trackeada es inválida (sin lock, o menos
        de `min_frames` frames procesados).
        """
        raise NotImplementedError
