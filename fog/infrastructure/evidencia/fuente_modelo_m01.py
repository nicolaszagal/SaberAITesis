"""Adaptador de FuenteEvidenciaModeloPort: extrae la tabla resumen de M01
de `dataset/lstm_6class/EXPERIMENT_LOG.md` (solo lectura).

La sección empieza en el encabezado `## Tabla resumen` y termina en la
siguiente línea `---`. Si el archivo no existe o hay más de una sección con
ese encabezado, no hay tabla (None): no se adivina cuál es la correcta.
"""

from __future__ import annotations

from pathlib import Path

from fog.ports.fuente_evidencia_modelo import FuenteEvidenciaModeloPort

ENCABEZADO = "## Tabla resumen"


class FuenteModeloM01(FuenteEvidenciaModeloPort):
    def __init__(self, ruta_log: str | Path | None):
        """Guarda la ruta del log de experimentos.

        Args:
            ruta_log: `EXPERIMENT_LOG.md` de `dataset/lstm_6class`; None si
                no está configurado.
        """
        self._ruta = Path(ruta_log) if ruta_log else None

    def tabla_resumen_m01(self) -> str | None:
        if self._ruta is None or not self._ruta.is_file():
            return None
        lineas = self._ruta.read_text(encoding="utf-8").splitlines()
        inicios = [i for i, x in enumerate(lineas) if x.startswith(ENCABEZADO)]
        if len(inicios) != 1:
            return None
        seccion = []
        for linea in lineas[inicios[0]:]:
            if linea.strip() == "---":
                break
            seccion.append(linea)
        return "\n".join(seccion).strip()
