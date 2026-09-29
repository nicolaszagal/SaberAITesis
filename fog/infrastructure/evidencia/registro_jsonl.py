"""Adaptador del log de evidencia: logger `sabre.evidencia` a JSON Lines.

Cada línea va a `EVIDENCE_DIR/<evento_id>.jsonl`. El logger no propaga al
log técnico. Un único manejador (compartido por el proceso) enruta cada
registro al archivo de su evento según los datos que trae el `LogRecord`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from fog.domain.evidencia import LineaEvidencia
from fog.ports.registro_evidencia import RegistroEvidenciaPort

NOMBRE_LOGGER = "sabre.evidencia"


class ManejadorEvidencia(logging.Handler):
    """Escribe el mensaje del registro (ya JSON) al archivo de su evento."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ruta = Path(record.evidencia_dir) / f"{record.evento_id}.jsonl"
            with ruta.open("a", encoding="utf-8") as archivo:
                archivo.write(record.getMessage() + "\n")
        except Exception:
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        # Un fallo de escritura no debe perderse en silencio: se propaga al
        # que llama a `registrar`.
        raise


def _logger_de_evidencia() -> logging.Logger:
    logger = logging.getLogger(NOMBRE_LOGGER)
    if not any(isinstance(h, ManejadorEvidencia) for h in logger.handlers):
        logger.addHandler(ManejadorEvidencia())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


class RegistroEvidenciaJsonl(RegistroEvidenciaPort):
    def __init__(self, directorio: str | Path | None):
        """Prepara el directorio de evidencia.

        Args:
            directorio: EVIDENCE_DIR; se crea si no existe.

        Raises:
            RuntimeError: si `directorio` no está definido.
        """
        if not directorio:
            raise RuntimeError("EVIDENCE_DIR no está definido: no hay dónde registrar")
        self._directorio = Path(directorio)
        self._directorio.mkdir(parents=True, exist_ok=True)
        self._logger = _logger_de_evidencia()

    def registrar(self, linea: LineaEvidencia) -> None:
        """Agrega la línea JSON al archivo del evento.

        Args:
            linea: campos de evidencia de la revisión cerrada.

        Raises:
            OSError: si no se puede escribir el archivo.
        """
        self._logger.info(
            json.dumps(asdict(linea), ensure_ascii=False),
            extra={
                "evidencia_dir": str(self._directorio),
                "evento_id": linea.evento_id,
            },
        )
