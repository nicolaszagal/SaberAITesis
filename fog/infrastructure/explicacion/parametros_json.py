"""Adaptador de ParametrosExplicacionPort sobre `fog/config/explicacion_params.json`."""

from __future__ import annotations

import json
from pathlib import Path

from fog.domain.razonamiento import ParametrosExplicacion
from fog.ports.parametros_explicacion import ParametrosExplicacionPort

RUTA_POR_DEFECTO = (
    Path(__file__).resolve().parents[2] / "config" / "explicacion_params.json"
)


class ParametrosExplicacionJson(ParametrosExplicacionPort):
    def __init__(self, ruta: str | Path | None = None):
        self._ruta = Path(ruta) if ruta else RUTA_POR_DEFECTO

    def cargar(self) -> ParametrosExplicacion:
        """Lee y valida el archivo de parámetros.

        Returns:
            Los parámetros U1 a U6 con su versión.

        Raises:
            ValueError: si falta una clave, un valor es no positivo o falta el
                artículo de alguna familia de clase.
        """
        datos = json.loads(self._ruta.read_text(encoding="utf-8"))
        try:
            params = ParametrosExplicacion(
                version=str(datos["version"]),
                u1_angulo_min=float(datos["u1"]["angulo_min_grados"]),
                u1_incrementos_min=int(datos["u1"]["incrementos_min"]),
                u2_umbral=float(datos["u2"]["umbral_rel_vel"]),
                u2_frames_sostenidos=int(datos["u2"]["frames_sostenidos"]),
                u2_frames_censura=int(datos["u2"]["frames_censura"]),
                u3_margen_frames=int(datos["u3"]["margen_frames"]),
                u4_articulos=dict(datos["u4"]["articulos"]),
                u5_masa_atencion=float(datos["u5"]["masa_atencion"]),
                u6_max_frases=int(datos["u6"]["max_frases"]),
                u6_max_caracteres=int(datos["u6"]["max_caracteres"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"{self._ruta}: parámetro faltante o mal formado ({exc!r})"
            ) from exc
        if (
            min(
                params.u1_incrementos_min,
                params.u2_frames_sostenidos,
                params.u3_margen_frames,
                params.u6_max_frases,
                params.u6_max_caracteres,
            )
            < 1
            or params.u2_umbral <= 0
            or not 0 < params.u5_masa_atencion <= 1
            or not {"Attack", "Contrattack", "Riposte"} <= set(params.u4_articulos)
        ):
            raise ValueError(f"{self._ruta}: valores fuera de rango")
        return params
