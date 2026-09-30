"""ClasificacionRepositoryPort — persistencia de `sabre.clasificacion`
(CU-06). Sin update ni delete: el trigger `tg_clasificacion_inmutable` los
bloquea igual (RNF-05), así que el puerto no los expone.

`clase` y las llaves de `probabilidades` van con los nombres del modelo
(`AttackA`, ...); el adaptador de persistencia los traduce al esquema.
"""

import uuid
from abc import ABC, abstractmethod

from fog.domain.audit_models import Clasificacion


class ClasificacionRepositoryPort(ABC):
    @abstractmethod
    async def crear(
        self,
        *,
        tocado_id: uuid.UUID,
        modelo_version_id: uuid.UUID,
        disponible: bool,
        keypoints_uri: str,
        keypoints_sha256: str,
        motivo_no_disp: str | None = None,
        clase: str | None = None,
        tirador: str | None = None,
        confianza: float | None = None,
        probabilidades: dict | None = None,
        features_uri: str | None = None,
        latencia_ms: int | None = None,
        latencia_inferencia_ms: int | None = None,
    ) -> Clasificacion:
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, clasificacion_id: uuid.UUID) -> Clasificacion | None:
        raise NotImplementedError

    @abstractmethod
    async def obtener_por_tocado_y_modelo(
        self, tocado_id: uuid.UUID, modelo_version_id: uuid.UUID
    ) -> Clasificacion | None:
        raise NotImplementedError
