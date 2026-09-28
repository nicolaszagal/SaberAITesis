"""LocalFileStorage — adaptador de FileStoragePort sobre disco local.

Layout bajo STORAGE_DIR (en Docker, el volumen montado ahí):

    clips/<sha[:2]>/<sha>.<ext>
    keypoints/<sha[:2]>/<sha>.npz

El nombre es el SHA-256 del contenido, así que guardar dos veces el mismo
archivo no lo duplica. La URI devuelta usa el esquema `local://` y es
relativa a STORAGE_DIR, para que siga válida si el volumen se monta en otra
ruta o se migra a un almacén de objetos.
"""

import asyncio
import hashlib
import io
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from fog.ports.file_storage import FileStoragePort

_CHUNK = 1024 * 1024
URI_SCHEME = "local://"


class LocalFileStorage(FileStoragePort):
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    async def save_clip(self, source: Path) -> tuple[str, str]:
        return await asyncio.to_thread(self._save_clip, Path(source))

    async def save_keypoints(self, arrays: Mapping[str, np.ndarray]) -> tuple[str, str]:
        return await asyncio.to_thread(self._save_keypoints, arrays)

    def _save_clip(self, source: Path) -> tuple[str, str]:
        digest = hashlib.sha256()
        with source.open("rb") as f:
            while chunk := f.read(_CHUNK):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        rel = self._relative("clips", sha256, source.suffix.lower())
        self._place(rel, lambda tmp: self._copy(source, tmp))
        return URI_SCHEME + rel.as_posix(), sha256

    def _save_keypoints(self, arrays: Mapping[str, np.ndarray]) -> tuple[str, str]:
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        data = buffer.getvalue()
        sha256 = hashlib.sha256(data).hexdigest()
        rel = self._relative("keypoints", sha256, ".npz")
        self._place(rel, lambda tmp: tmp.write_bytes(data))
        return URI_SCHEME + rel.as_posix(), sha256

    @staticmethod
    def _relative(kind: str, sha256: str, suffix: str) -> Path:
        return Path(kind) / sha256[:2] / f"{sha256}{suffix}"

    @staticmethod
    def _copy(source: Path, destination: Path) -> None:
        with source.open("rb") as src, destination.open("wb") as dst:
            while chunk := src.read(_CHUNK):
                dst.write(chunk)

    def _place(self, rel: Path, write) -> None:
        """Escribe en un temporal y lo renombra: nunca queda un archivo a medias."""
        final = self._root / rel
        if final.exists():
            return
        final.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=final.parent, suffix=".tmp")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            write(tmp)
            os.replace(tmp, final)
        finally:
            tmp.unlink(missing_ok=True)
