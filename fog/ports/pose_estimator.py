"""PoseEstimatorPort — detección+tracking de personas, frame a frame.

Cambiado de "lista de frames -> TrackedSequence" a un patrón de sesión
streaming (start_session/add_frame/finish) por dos razones a la vez
(decisión de Nicolas, 2026-06-22, de no diferir el fix de concurrencia):

1. Permite procesar cada frame en cuanto llega por WebRTC, en vez de
   esperar a que el clip completo termine para recién ahí arrancar
   pose+features (antes 100% serial: tiempo real del clip + tiempo de
   CPU de pose+features, uno después del otro).
2. Aísla el estado de tracking por combate: antes, model.track(...,
   persist=True) reutilizaba un único tracker interno de ultralytics
   compartido por TODAS las llamadas a ese modelo — si dos combates
   corrían en paralelo (dos nodos Edge simultáneos), sus IDs de
   tracking se mezclaban entre sí. Con start_session(), cada combate
   tiene su propio tracker. El modelo YOLO en sí (pesos, inferencia)
   sigue siendo un Singleton compartido — ver YoloV8PoseAdapter.

Implementación de referencia: infrastructure/pose/yolo_pose_adapter.py
(YOLOv8x-pose + BoT-SORT vía ultralytics, instanciado manualmente por
sesión). Para migrar a otro detector (ej. YOLOv8n, MediaPipe) solo se
necesita una nueva clase que cumpla este puerto — nada en application/
ni en FeatureExtractorPort depende de ultralytics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from fog.domain.models import TrackedSequence


class PoseTrackingSession(ABC):
    """Una instancia por combate. No es thread-safe en sí misma: el
    llamador (track_consumer.py) debe invocar add_frame secuencialmente
    para un mismo combate — el orden de los frames es parte del estado
    del tracker (Kalman filter, IDs), igual que el loop sobre `frames`
    que reemplaza."""

    @abstractmethod
    def add_frame(self, frame: np.ndarray) -> None:
        raise NotImplementedError

    @abstractmethod
    def finish(self) -> TrackedSequence:
        """Cierra la sesión y devuelve la TrackedSequence acumulada. No
        se debe llamar add_frame después de finish()."""
        raise NotImplementedError


class PoseEstimatorPort(ABC):
    @abstractmethod
    def start_session(self) -> PoseTrackingSession:
        raise NotImplementedError
