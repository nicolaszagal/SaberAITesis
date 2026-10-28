"""Informe `razonamiento_v1.md` del análisis descriptivo del razonamiento.

Escribe en `EVIDENCE_DIR/<evento_id>/razonamiento_v1.md` la tabla de resumen
de las revisiones de la Validación 1 junto a la de una muestra de clips de
entrenamiento. No es una métrica de aceptación.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fog.application.analizar_razonamiento import AnalisisEvento
from fog.domain.analisis_razonamiento import ClipAnalizado, ResumenMuestra, resumir

NOMBRE_ARCHIVO = "razonamiento_v1.md"
_CAUSA_TEXTO = {
    "sin_subida": "sin subida sostenida del codo",
    "deteccion": "hueco de detección",
}


def cargar_muestra_train(ruta: Path) -> tuple[dict, list[ClipAnalizado]]:
    """Lee la muestra de clips de entrenamiento (JSON con `descripcion` y `clips`).

    Args:
        ruta: archivo JSON.

    Returns:
        (metadatos de la muestra, clips analizados).
    """
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    clips = [
        ClipAnalizado(
            clip=c["clip"],
            clase=c["clase"],
            estado=c["estado"],
            causa=c["causa"],
            u1_censurados=tuple(c["u1_censurados"]),
            u2=c["u2"],
            lock_frame=c["lock_frame"],
        )
        for c in datos["clips"]
    ]
    return {k: v for k, v in datos.items() if k != "clips"}, clips


def _pct(k: int, n: int) -> str:
    return f"{k} ({100 * k / n:.1f} %)" if n else "0"


def _filas(r: ResumenMuestra) -> list[tuple[str, str]]:
    n = r.n
    filas: list[tuple[str, str]] = [("Clips analizados", str(n))]
    for estado, k in r.estados.items():
        filas.append((f"Estado `{estado}`", _pct(k, n)))
    insuf = r.estados.get("insuficiente", 0)
    for causa, k in r.causas_insuficiente.items():
        filas.append(
            (f"  causa de `insuficiente`: {_CAUSA_TEXTO[causa]}", _pct(k, insuf))
        )
    filas.append(
        ("U1: clips con algún inicio censurado", _pct(r.u1_clips_con_censura, n))
    )
    filas.append(
        ("U1: clips con ambos censurados", _pct(r.u1_clips_ambos_censurados, n))
    )
    filas.append(("U2: clips con inicio de desplazamiento", _pct(r.u2_con_inicio, n)))
    filas.append(
        (
            "U2: inicios censurados (de los que tienen inicio)",
            _pct(r.u2_censurados, r.u2_con_inicio),
        )
    )
    for tramo, k in r.lock_tramos.items():
        filas.append((f"`lock_frame` {tramo}", _pct(k, n)))
    if r.lock_mediana is not None:
        filas.append(
            (
                "`lock_frame` mín / mediana / máx",
                f"{r.lock_min} / {r.lock_mediana:g} / {r.lock_max}",
            )
        )
    return filas


def render(
    analisis: AnalisisEvento,
    train: tuple[dict, list[ClipAnalizado]] | None = None,
    generado_en: datetime | None = None,
) -> str:
    """Arma el Markdown del informe.

    Args:
        analisis: análisis de las revisiones del evento.
        train: muestra de entrenamiento (metadatos, clips) para comparar, o None.
        generado_en: instante de generación (por defecto, ahora en UTC).

    Returns:
        El contenido de `razonamiento_v1.md`.
    """
    v1 = resumir(analisis.clips)
    tr = resumir(train[1]) if train else None
    ahora = (generado_en or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    lineas = [
        "# Razonamiento de la sugerencia: Validación 1 frente a clips de entrenamiento",
        "",
        f"Evento `{analisis.evento_id}` · parámetros versión "
        f"`{analisis.params_version}` · "
        f"generado {ahora}.",
        "",
        "Análisis **descriptivo y de solo lectura**: el razonamiento se calculó en "
        "memoria "
        "con los parámetros vigentes; no se escribió en `evidencia` ni en la "
        "auditoría (D-17) "
        "y no es una métrica de aceptación.",
        "",
    ]
    cabecera = ["Medida", f"Validación 1 (n = {v1.n})"]
    if tr:
        cabecera.append(f"Clips de train (n = {tr.n})")
    lineas.append("| " + " | ".join(cabecera) + " |")
    lineas.append("|" + "|".join(["---"] + ["---:"] * (len(cabecera) - 1)) + "|")
    f1 = _filas(v1)
    f2 = _filas(tr) if tr else None
    for i, (nombre, valor) in enumerate(f1):
        celdas = [nombre, valor] + ([f2[i][1]] if f2 else [])
        lineas.append("| " + " | ".join(celdas) + " |")
    lineas += ["", "## Notas", ""]
    lineas.append(
        f"- Revisiones del evento: {analisis.revisiones_total}; analizadas: {v1.n}."
    )
    if analisis.omitidas:
        detalle = ", ".join(f"{k}: {v}" for k, v in sorted(analisis.omitidas.items()))
        lineas.append(f"- Omitidas por motivo: {detalle}.")
    else:
        lineas.append("- No se omitió ninguna revisión.")
    lineas.append(
        "- Sin ventana de atención: Fog no guarda los pesos de atención, solo la "
        "ventana "
        "registrada; no cambia el estado ni los eventos."
    )
    if train:
        meta = train[0]
        lineas.append(
            "- Clips de train: "
            f"{meta.get('descripcion', 'muestra de clips de entrenamiento')}"
        )
    else:
        lineas.append("- Sin muestra de train: no se indicó `--muestra-train`.")
    lineas.append(
        "- Los porcentajes de causas de `insuficiente` son sobre los clips "
        "`insuficiente`; "
        "los de U2, sobre los clips con inicio de desplazamiento."
    )
    return "\n".join(lineas) + "\n"


def escribir(
    directorio: str | Path,
    analisis: AnalisisEvento,
    train: tuple[dict, list[ClipAnalizado]] | None = None,
) -> Path:
    """Escribe `<directorio>/<evento_id>/razonamiento_v1.md`.

    Args:
        directorio: `EVIDENCE_DIR`.
        analisis: análisis del evento.
        train: muestra de entrenamiento para comparar, o None.

    Returns:
        La ruta del archivo escrito.

    Raises:
        RuntimeError: si `directorio` no está definido.
    """
    if not directorio:
        raise RuntimeError("EVIDENCE_DIR no está definido: no hay dónde escribir")
    carpeta = Path(directorio) / str(analisis.evento_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / NOMBRE_ARCHIVO
    destino.write_text(render(analisis, train), encoding="utf-8")
    return destino
