"""PurgarClips — ningún clip se conserva después de la sesión (EDGE02, datos personales).

Borra los archivos de video del almacén de Fog. En la base se conservan `clip.sha256` y los
metadatos: el registro de auditoría sigue verificable (`fn_verificar_auditoria()`) aunque el
archivo ya no exista. Se corre DESPUÉS del respaldo, que excluye los clips.
"""

from __future__ import annotations

import logging
import uuid

from fog.ports.file_storage import FileStoragePort
from fog.ports.tocados_repository import TocadosRepositoryPort

log = logging.getLogger("fog.application")


class PurgarClips:
    def __init__(self, tocados: TocadosRepositoryPort, storage: FileStoragePort):
        self._tocados = tocados
        self._storage = storage

    async def execute(self, combate_id: uuid.UUID | None = None) -> int:
        """Borra los archivos de clip.

        Args:
            combate_id: solo los clips de ese combate; `None` = todos los de la base.

        Returns:
            Cuántos archivos se borraron (los que ya no existían no cuentan).
        """
        borrados = 0
        for uri in set(await self._tocados.uris_clips(combate_id)):
            if await self._storage.eliminar_clip(uri):
                borrados += 1
        log.info("clips purgados: %d archivo(s)", borrados)
        return borrados
