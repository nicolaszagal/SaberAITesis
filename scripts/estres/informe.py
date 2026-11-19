"""ESTRES01: tablas en Markdown y gráfica p50/p95 contra número de pistas, a partir de los resúmenes de `desglosar.py`.

Uso: .venv/bin/python scripts/estres/informe.py --local-a A.json --local-b B.json --remoto-a R.json \\
        --png salida.png --tablas tablas.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ETAPAS = ["subida", "cola_executor", "cola_yolo", "pose", "features", "cloud_espera", "clasificacion", "resto"]
ENCABEZADO = ("| Pistas | n | p50 (s) | p95 (s) | máx (s) | No disponibles | > 60 s | subida | cola executor | cola YOLO "
              "| pose | features | espera Cloud | clasificación | resto | CPU Fog máx | RAM Fog máx (MiB) |\n"
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def _f(v: float | None, d: int = 1) -> str:
    """Formatea un número con `d` decimales, o `n/d` si no se pudo medir."""
    return "n/d" if v is None else f"{v:.{d}f}"


def tabla(datos: dict, filas: list[tuple[str, str]]) -> str:
    """Arma la tabla Markdown de un escenario.

    Args:
        datos: salida de `desglosar.py` (`resumen` y `recursos_max`).
        filas: pares `(clave del resumen, etiqueta de pistas)`.

    Returns:
        La tabla en Markdown (etapas = media por solicitud, en segundos).
    """
    lineas = [ENCABEZADO]
    for clave, etiqueta in filas:
        r = datos["resumen"][clave]
        rec = datos["recursos_max"].get(clave) or next(iter(datos["recursos_max"].values()), {})
        e = r["etapas_media"]
        lineas.append(
            f"| {etiqueta} | {r['n']} | {_f(r['p50'])} | {_f(r['p95'])} | {_f(r['max'])} | {r['no_disponibles']} "
            f"| {r['fuera_de_60s']} | " + " | ".join(_f(e[x], 2) for x in ETAPAS)
            + f" | {_f(rec.get('fog_cpu_pct'), 0)} % | {_f(rec.get('fog_rss_mib'), 0)} |"
        )
    return "\n".join(lineas)


def main() -> None:
    """Escribe las tablas y la gráfica."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-a", required=True)
    ap.add_argument("--local-b", required=True)
    ap.add_argument("--remoto-a", required=True)
    ap.add_argument("--png", required=True)
    ap.add_argument("--tablas", required=True)
    a = ap.parse_args()
    la, lb, ra = (json.loads(Path(p).read_text()) for p in (a.local_a, a.local_b, a.remoto_a))
    Path(a.tablas).write_text(
        "### A local (ráfaga)\n\n" + tabla(la, [(f"A_n{n}", str(n)) for n in (1, 2, 3, 4)])
        + "\n\n### B local (sostenido, 10 min × 3 repeticiones)\n\n" + tabla(lb, [("B_n4", "4")])
        + "\n\n### A desplegado (ráfaga, 4 pistas, 1 repetición)\n\n" + tabla(ra, [("A_n4", "4")]) + "\n"
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [1, 2, 3, 4]
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(xs, [la["resumen"][f"A_n{n}"]["p50"] for n in xs], "o-", label="p50 local")
    ax.plot(xs, [la["resumen"][f"A_n{n}"]["p95"] for n in xs], "s--", label="p95 local")
    ax.plot([4], [ra["resumen"]["A_n4"]["p95"]], "^", color="tab:green", label="p95 desplegado (n=4, 1 rep.)")
    ax.axhline(60, color="tab:red", linestyle=":", label="RNF-04: 60 s")
    ax.set_xticks(xs)
    ax.set_xlabel("Pistas con revisión simultánea")
    ax.set_ylabel("Latencia total por clip (s)")
    ax.set_title("ESTRES01 · Escenario A (ráfaga)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(a.png, dpi=150)


if __name__ == "__main__":
    main()
