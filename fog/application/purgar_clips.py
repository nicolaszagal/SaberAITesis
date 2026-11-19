"""PurgarClips — ningún clip se conserva después de la sesión (EDGE02, D-22, datos personales).

Borra los archivos de video del almacén de Fog. En la base se conservan `clip.sha256` y los metadatos:
el registro de auditoría sigue verificable (`fn_verificar_auditoria()`) aunque el archivo ya no exista.
Se corre DESPUÉS del respaldo, que excluye los clips.
"""

from __future__ import annotations

import logging
import uuid

from fog.ports.clip_repository import ClipRepositoryPort
from fog.ports.file_storage import FileStoragePort

log = logging.getLogger("fog.application")


class PurgarClips:
    def __init__(self, clips: ClipRepositoryPort, storage: FileStoragePort):
        self._clips = clips
        self._storage = storage

    async def execute(self, evento_id: uuid.UUID) -> int:
        """Borra los archivos de clip de una sesión.

        Args:
            evento_id: sesión (evento) cuyos clips se borran. Un archivo que otra sesión también usa
                (mismo hash) no se toca.

        Returns:
            Cuántos archivos se borraron (los que ya no existían no cuentan).
        """
        borrados = 0
        for uri in await self._clips.uris_de_sesion(evento_id):
            if await self._storage.eliminar_clip(uri):
                borrados += 1
        log.info("clips purgados: %d archivo(s)", borrados)
        return borrados
