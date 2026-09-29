"""ModeloVersionRepositoryPort — persistencia de `sabre.modelo_version`
(CU-06, CU-13; scripts/registrar_modelo.py).

Solo una versión puede estar activa a la vez (`ux_modelo_activo`, índice
único parcial sobre `activo`). `registrar` desactiva la versión activa
anterior (si hay una) en la misma transacción antes de insertar la nueva
con `activo=activar` — así nunca hay una ventana con dos filas `activo`.
"""

import uuid
from abc import ABC, abstractmethod

from fog.domain.audit_models import ModeloVersion


class ModeloVersionRepositoryPort(ABC):
    @abstractmethod
    async def registrar(
        self,
        *,
        nombre: str,
        checkpoint_uri: str,
        checkpoint_sha256: str,
        pose_modelo: str,
        num_features: int,
        num_clases: int,
        f1_macro_test: float | None = None,
        kappa_piloto: float | None = None,
        padre_id: uuid.UUID | None = None,
        activar: bool = True,
    ) -> ModeloVersion:
        raise NotImplementedError

    @abstractmethod
    async def obtener_activo(self) -> ModeloVersion | None:
        raise NotImplementedError

    @abstractmethod
    async def obtener(self, modelo_version_id: uuid.UUID) -> ModeloVersion | None:
        raise NotImplementedError
