"""Exportación de la evidencia de una sesión de validación (L02).

Escribe en `EVIDENCE_DIR/<evento_id>/`: `resumen.json`, `revisiones.csv`
(los 16 campos de L01, mismo orden, armados desde la base) y `resumen.md`
(como máximo una pantalla). Idempotente: reescribe los tres archivos y, con
los mismos datos, solo cambia `generado_en`.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from fog.application.resumir_validacion import ResumenValidacion
from fog.domain.evidencia import LineaEvidencia

ETIQUETA_VALIDACION = {"V1": "tocado simulado", "V2": "señal Favero"}


def _celda(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def renderizar_csv(lineas: list[LineaEvidencia]) -> str:
    """Genera `revisiones.csv` con los campos de L01 en su orden.

    Args:
        lineas: líneas armadas con `construir_linea`.

    Returns:
        El CSV con encabezado; booleanos en minúscula, nulos vacíos.
    """
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow([f.name for f in fields(LineaEvidencia)])
    for linea in lineas:
        escritor.writerow([_celda(v) for v in asdict(linea).values()])
    return salida.getvalue()


def _cumple(valor: bool | None) -> str:
    return {True: "cumple", False: "no cumple", None: "sin datos"}[valor]


def _numero(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:g}"


def _bloque_validacion(nombre: str, m: dict[str, Any]) -> list[str]:
    nd = m["no_disponibles"]
    motivos = ", ".join(f"{k} {v}" for k, v in nd["por_motivo"].items() if v)
    lat = m["latencia"]
    if lat["p95_excede_umbral"]:
        texto_p95 = "> 60 s"
    else:
        texto_p95 = f"{_numero(lat['p95_ms'])} ms"
    kappa = m["kappa"]
    if kappa["calculable"]:
        texto_kappa = (
            f"{kappa['kappa']:g} ({kappa['banda']}), N={kappa['n']}, "
            f"umbral {kappa['umbral']:g}: {_cumple(kappa['cumple'])}"
        )
    else:
        texto_kappa = f"no calculable ({kappa['motivo']})"
    pct = m["concordancia"]["pct"]
    matriz = m["matriz_confusion"]
    lineas = [
        f"## {nombre} ({ETIQUETA_VALIDACION[nombre]})",
        f"- Revisiones: {m['n_revisiones']} · disponibles {m['disponibles']} · "
        f"no disponibles {nd['n']}" + (f" ({motivos})" if motivos else ""),
        f"- Latencia (N total={lat['n_total']} · disponibles={lat['n_disponibles']} · "
        f"no disponibles={lat['n_no_disponibles']}): "
        f"mediana {_numero(lat['mediana_ms'])} ms · máx {_numero(lat['max_ms'])} ms "
        "(solo disponibles) · "
        f"p95 {texto_p95} · ≤ 60 s {_numero(lat['pct_le_60s'])} % "
        "(sobre todas; no disponible = > 60 s)",
        f"- Umbral p95 ≤ {lat['umbral_ms']} ms: {_cumple(lat['cumple'])}",
        f"- κ de Cohen: {texto_kappa}",
        f"- Concordancia: {_numero(pct)} % (n={m['concordancia']['n']})",
    ]
    if not m["concordancia"]["n"]:
        return lineas + ["- Matriz de confusión: sin revisiones comparables"]
    lineas += [
        "",
        "| sistema \\ árbitro | " + " | ".join(matriz["clases"]) + " |",
        "|---|" + "---|" * len(matriz["clases"]),
    ]
    for clase, fila in zip(matriz["clases"], matriz["matriz"]):
        lineas.append(f"| {clase} | " + " | ".join(str(x) for x in fila) + " |")
    return lineas


def renderizar_md(resumen: dict[str, Any]) -> str:
    """Genera `resumen.md`: métricas, umbrales, conciliación e integridad.

    Args:
        resumen: contenido de `resumen.json`.

    Returns:
        El Markdown, sin texto decorativo.
    """
    c = resumen["conciliacion"]
    i = resumen["integridad"]
    modelo = resumen["modelo"]
    activo = modelo["activo"]
    ilegibles = (
        f" · líneas ilegibles: {c['lineas_ilegibles']}" if c["lineas_ilegibles"] else ""
    )
    usados = ", ".join(modelo["modelos_en_revisiones"]) or "—"
    tabla_m01 = (
        "en resumen.json (modelo.tabla_m01)" if modelo["tabla_m01"] else "no disponible"
    )
    lineas = [
        f"# Resumen de validación · evento {resumen['evento_id']}",
        f"Generado: {resumen['generado_en']}",
        "",
    ]
    for nombre in ("V1", "V2"):
        lineas += _bloque_validacion(nombre, resumen["por_validacion"][nombre]) + [""]
    lineas += [
        "## Conciliación con el JSONL",
        f"- En base: {c['n_base']} · en JSONL: {c['n_jsonl']}"
        + ("" if c["jsonl_presente"] else " (archivo ausente)")
        + ilegibles,
        f"- Faltantes en JSONL: {', '.join(c['faltantes_en_jsonl']) or 'ninguno'}",
        f"- Sobrantes en JSONL: {', '.join(c['sobrantes_en_jsonl']) or 'ninguno'}",
        "",
        "## Integridad",
        f"- sabre.fn_verificar_auditoria: {i['fn_verificar_auditoria']} "
        f"({i['registros_alterados']} registros alterados, cadena completa)",
        "",
        "## Modelo (referencia offline, no se recalcula F1)",
        "- Activo: "
        + (
            "sin versión activa"
            if activo is None
            else f"{activo['nombre']} · {activo['num_clases']} clases · "
            f"F1 macro test {_numero(activo['f1_macro_test'])} · "
            f"κ piloto {_numero(activo['kappa_piloto'])} (registrados)"
        ),
        f"- Usado en las revisiones: {usados}",
        f"- Tabla M01: {tabla_m01}",
    ]
    return "\n".join(lineas) + "\n"


class ExportadorEvidencia:
    def __init__(self, directorio: str | Path | None):
        """Prepara la exportación.

        Args:
            directorio: EVIDENCE_DIR; la salida va a `<directorio>/<evento_id>/`.

        Raises:
            RuntimeError: si `directorio` no está definido.
        """
        if not directorio:
            raise RuntimeError("EVIDENCE_DIR no está definido: no hay dónde exportar")
        self._directorio = Path(directorio)

    def exportar(self, resultado: ResumenValidacion) -> Path:
        """Escribe `resumen.json`, `revisiones.csv` y `resumen.md`.

        Args:
            resultado: resumen y líneas de una sesión.

        Returns:
            La carpeta `EVIDENCE_DIR/<evento_id>/`.

        Raises:
            OSError: si no se puede escribir.
        """
        carpeta = self._directorio / resultado.resumen["evento_id"]
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "resumen.json").write_text(
            json.dumps(resultado.resumen, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (carpeta / "revisiones.csv").write_text(
            renderizar_csv(resultado.lineas), encoding="utf-8"
        )
        (carpeta / "resumen.md").write_text(
            renderizar_md(resultado.resumen), encoding="utf-8"
        )
        return carpeta
