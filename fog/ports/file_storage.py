"""FileStoragePort — almacenamiento de binarios pesados (clips y keypoints).

La base de datos no guarda videos ni keypoints: guarda su URI y su SHA-256
(ver docs_claude/sabre_ai_schema.sql, tablas `clip` y `clasificacion`). Este
puerto guarda el archivo direccionado por su hash y devuelve ambos datos.
Hoy solo existe el adaptador de disco local; un almacén de objetos (MinIO)
sería otro adaptador sin tocar application/.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path

import numpy as np


class FileStoragePort(ABC):
    @abstractmethod
    async def save_clip(self, source: Path) -> tuple[str, str]:
        """Guarda un clip de video por su SHA-256.

        Args:
            source: archivo local ya escrito (por ejemplo el temporal de la
                subida). Se lee en bloques; el original no se modifica.

        Returns:
            Tupla (uri, sha256) con el SHA-256 en hexadecimal minúscula.

        Raises:
            FileNotFoundError: si `source` no existe.
        """
        raise NotImplementedError

    @abstractmethod
    async def save_keypoints(self, arrays: Mapping[str, np.ndarray]) -> tuple[str, str]:
        """Guarda los keypoints crudos como .npz por su SHA-256.

        Args:
            arrays: arreglos a serializar, por nombre (formato de np.savez).

        Returns:
            Tupla (uri, sha256) del .npz guardado.
        """
        raise NotImplementedError
