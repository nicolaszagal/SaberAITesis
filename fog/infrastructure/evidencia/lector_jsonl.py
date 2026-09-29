"""Adaptador de LectorEvidenciaPort: lee `EVIDENCE_DIR/<evento_id>.jsonl`
(escrito por `RegistroEvidenciaJsonl`) sin modificarlo.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fog.ports.lector_evidencia import LectorEvidenciaPort, LecturaEvidencia


class LectorEvidenciaJsonl(LectorEvidenciaPort):
    def __init__(self, directorio: str | Path | None):
        """Guarda el directorio de evidencia.

        Args:
            directorio: EVIDENCE_DIR.

        Raises:
            RuntimeError: si `directorio` no está definido.
        """
        if not directorio:
            raise RuntimeError("EVIDENCE_DIR no está definido: no hay qué conciliar")
        self._directorio = Path(directorio)

    def leer(self, evento_id: uuid.UUID) -> LecturaEvidencia:
        ruta = self._directorio / f"{evento_id}.jsonl"
        if not ruta.is_file():
            return LecturaEvidencia(presente=False, revision_ids=[], lineas_ilegibles=0)
        ids: list[str] = []
        ilegibles = 0
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            try:
                ids.append(str(json.loads(linea)["revision_id"]))
            except (ValueError, KeyError, TypeError):
                ilegibles += 1
        return LecturaEvidencia(
            presente=True, revision_ids=ids, lineas_ilegibles=ilegibles
        )
