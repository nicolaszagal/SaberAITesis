"""Adaptador de CombateActivoPort en un archivo JSON (sobrevive a un reinicio de Fog)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path

from fog.ports.combate_activo import CombateActivoPort


class CombateActivoArchivo(CombateActivoPort):
    """Guarda el id del combate activo en `<directorio>/combate_activo.json`."""

    def __init__(self, directorio: str | Path) -> None:
        self._ruta = Path(directorio) / "combate_activo.json"
        self._lock = threading.Lock()

    def establecer(self, combate_id: uuid.UUID) -> None:
        with self._lock:
            self._ruta.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._ruta.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"match_id": str(combate_id)}, f)
            os.replace(tmp, self._ruta)

    def obtener(self) -> uuid.UUID | None:
        with self._lock:
            try:
                return uuid.UUID(json.loads(self._ruta.read_text(encoding="utf-8"))["match_id"])
            except (OSError, ValueError, KeyError, TypeError):
                return None

    def limpiar(self) -> None:
        with self._lock:
            self._ruta.unlink(missing_ok=True)
