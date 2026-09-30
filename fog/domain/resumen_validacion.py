"""Métricas del resumen de validación (L02, T-017, RNF-04, RNF-06).

Funciones puras sobre las líneas de evidencia de L01 (`LineaEvidencia`):
no leen base ni archivos. Solo se calculan las métricas de
`docs_claude/protocolo_validacion.md`: revisiones y disponibilidad,
latencia de la sugerencia (D-08), κ de Cohen sistema-árbitro con su banda
de Landis & Koch (RNF-06), concordancia simple y matriz de confusión 6 × 6.
No hay κ inter-árbitro: su protocolo no está definido.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from fog.domain.evidencia import LineaEvidencia
from fog.domain.models import CLASES_MODELO

# Umbrales documentados.
UMBRAL_LATENCIA_MS = 60_000  # D-08, RNF-04 (p95)
UMBRAL_INFERENCIA_MS = 50  # F-027: tiempo del clasificador por clip
UMBRAL_KAPPA = 0.61  # RNF-06

# Valores de `clasificacion.motivo_no_disp` (CHECK de sabre_ai_schema.sql).
MOTIVOS_NO_DISPONIBLE = (
    "pose_incompleta",
    "confianza_baja",
    "clase_fuera_mvp",
    "timeout",
    "sin_senal_favero",
    "mensaje_invalido",
)

VALIDACIONES = ("V1", "V2")

# Cota inferior de cada banda de Landis & Koch (1977), de mayor a menor.
# Se aplica sobre κ sin redondear, así κ ≥ 0.61 equivale a "sustancial" o más.
_BANDAS = (
    (0.81, "casi perfecta"),
    (0.61, "sustancial"),
    (0.41, "moderada"),
    (0.21, "aceptable"),
    (0.0, "leve"),
)


def banda_landis_koch(kappa: float) -> str:
    """Clasifica κ en la banda de Landis & Koch.

    Args:
        kappa: valor de κ de Cohen.

    Returns:
        `pobre` (< 0), `leve` (0 a 0.20), `aceptable` (0.21 a 0.40),
        `moderada` (0.41 a 0.60), `sustancial` (0.61 a 0.80) o
        `casi perfecta` (0.81 a 1.00).
    """
    for cota, nombre in _BANDAS:
        if kappa >= cota:
            return nombre
    return "pobre"


def cohen_kappa(sistema: Sequence[str], arbitro: Sequence[str]) -> dict[str, Any]:
    """Calcula κ de Cohen entre dos series de clases, sin dependencias.

    κ = (po − pe) / (1 − pe), con po la concordancia observada y pe la
    esperada por azar según las frecuencias marginales de cada lado. Se
    calcula con enteros: κ = (n·d − S) / (n² − S), con d los aciertos y
    S = Σ (total del sistema en la clase × total del árbitro en la clase).

    Args:
        sistema: clase sugerida por el sistema en cada revisión.
        arbitro: clase final del árbitro en las mismas revisiones.

    Returns:
        Diccionario con `n`, `calculable`, `kappa`, `banda`, `umbral`,
        `cumple` y `motivo`. Si no es calculable (n < 2, o una sola clase
        en ambos lados), `kappa`, `banda` y `cumple` son None y `motivo`
        explica la razón; nunca NaN ni 0.

    Raises:
        ValueError: si las series no tienen la misma longitud.
    """
    if len(sistema) != len(arbitro):
        raise ValueError("sistema y arbitro deben tener la misma longitud")
    n = len(sistema)
    resultado: dict[str, Any] = {
        "n": n,
        "calculable": False,
        "kappa": None,
        "banda": None,
        "umbral": UMBRAL_KAPPA,
        "cumple": None,
        "motivo": None,
    }
    if n < 2:
        resultado["motivo"] = f"N = {n} < 2 revisiones disponibles y no anuladas"
        return resultado
    aciertos = sum(1 for s, a in zip(sistema, arbitro) if s == a)
    clases = set(sistema) | set(arbitro)
    azar = sum(sistema.count(c) * arbitro.count(c) for c in clases)
    if azar == n * n:
        resultado["motivo"] = "una sola clase en ambos lados: κ indefinido"
        return resultado
    kappa = (n * aciertos - azar) / (n * n - azar)
    resultado.update(
        calculable=True,
        kappa=round(kappa, 4),
        banda=banda_landis_koch(kappa),
        cumple=kappa >= UMBRAL_KAPPA,
        motivo=None,
    )
    return resultado


def matriz_confusion(
    sistema: Sequence[str], arbitro: Sequence[str]
) -> dict[str, Any]:
    """Matriz de confusión 6 × 6 sistema (filas) vs. árbitro (columnas).

    Args:
        sistema: clase sugerida en cada revisión (nombres del modelo).
        arbitro: clase final del árbitro en las mismas revisiones.

    Returns:
        `clases` (orden de `CLASES_MODELO`), `filas`, `columnas` y `matriz`.

    Raises:
        ValueError: si alguna clase no es del modelo o las series difieren
            en longitud.
    """
    if len(sistema) != len(arbitro):
        raise ValueError("sistema y arbitro deben tener la misma longitud")
    indice = {clase: i for i, clase in enumerate(CLASES_MODELO)}
    matriz = [[0] * len(CLASES_MODELO) for _ in CLASES_MODELO]
    for s, a in zip(sistema, arbitro):
        matriz[indice[s]][indice[a]] += 1
    return {
        "clases": list(CLASES_MODELO),
        "filas": "sistema",
        "columnas": "arbitro",
        "matriz": matriz,
    }


def _percentil_nearest_rank(ordenados: Sequence[float], porcentaje: int) -> float:
    """Percentil por rango más cercano: el elemento ceil(p·n/100)-ésimo."""
    posicion = math.ceil(porcentaje * len(ordenados) / 100)
    return ordenados[max(posicion, 1) - 1]


def resumen_latencia(
    latencias_disponibles_ms: Sequence[int | None], n_no_disponibles: int
) -> dict[str, Any]:
    """Estadísticos de la latencia de la sugerencia (D-08, RNF-04).

    La latencia es el tiempo hasta que la sugerencia está disponible
    (`protocolo_validacion.md`), así que una revisión no disponible no tiene
    una latencia que medir. Por eso:

    - Mediana y máximo: solo sobre las revisiones disponibles.
    - % ≤ 60 s y p95 (rango más cercano): sobre todas las revisiones; las no
      disponibles cuentan como > 60 s. Si más del 5 % no está disponible, el
      p95 cae en una no disponible y se reporta como "> 60 s".

    Una revisión disponible sin `latencia_ms` no se puede medir: queda fuera
    de todos los cálculos y se cuenta en `sin_medicion`.

    Args:
        latencias_disponibles_ms: `latencia_ms` de cada revisión disponible
            (None si no se registró).
        n_no_disponibles: cantidad de revisiones no disponibles.

    Returns:
        `n_total`, `n_disponibles`, `n_no_disponibles`, `sin_medicion`,
        `mediana_ms` y `max_ms` (disponibles), `p95_ms` (None si es
        "> 60 s" o no hay datos), `p95_excede_umbral` (True si el p95 es
        "> 60 s"), `pct_le_60s`, `umbral_ms` y `cumple` (p95 ≤ 60 s, RNF-04).
        Sin revisiones medibles, los valores son None.
    """
    medidas = sorted(x for x in latencias_disponibles_ms if x is not None)
    n_disponibles = len(latencias_disponibles_ms)
    base = len(medidas) + n_no_disponibles
    resultado: dict[str, Any] = {
        "n_total": n_disponibles + n_no_disponibles,
        "n_disponibles": n_disponibles,
        "n_no_disponibles": n_no_disponibles,
        "sin_medicion": n_disponibles - len(medidas),
        "mediana_ms": None,
        "max_ms": None,
        "p95_ms": None,
        "p95_excede_umbral": None,
        "pct_le_60s": None,
        "umbral_ms": UMBRAL_LATENCIA_MS,
        "cumple": None,
    }
    if base == 0:
        return resultado
    if medidas:
        mitad = len(medidas) // 2
        if len(medidas) % 2:
            resultado["mediana_ms"] = medidas[mitad]
        else:
            resultado["mediana_ms"] = (medidas[mitad - 1] + medidas[mitad]) / 2
        resultado["max_ms"] = medidas[-1]
    # Las no disponibles van al final como +inf: superan cualquier umbral.
    todas: list[float] = [*medidas, *([math.inf] * n_no_disponibles)]
    p95 = _percentil_nearest_rank(todas, 95)
    dentro = sum(1 for x in medidas if x <= UMBRAL_LATENCIA_MS)
    excede = p95 > UMBRAL_LATENCIA_MS
    resultado.update(
        p95_ms=None if math.isinf(p95) else p95,
        p95_excede_umbral=excede,
        pct_le_60s=round(100 * dentro / base, 2),
        cumple=not excede,
    )
    return resultado


def resumen_latencia_inferencia(
    latencias_disponibles_ms: Sequence[int | None],
) -> dict[str, Any]:
    """Estadísticos de la latencia de inferencia del clasificador (F-027).

    Se calcula sobre las revisiones disponibles (las no disponibles no
    tuvieron inferencia). Una disponible sin `latencia_inferencia_ms`
    (por ejemplo, registrada antes de la migración 0004) no se puede medir:
    queda fuera de todos los cálculos y se cuenta en `sin_medicion`.

    Args:
        latencias_disponibles_ms: `latencia_inferencia_ms` de cada revisión
            disponible (None si no se registró).

    Returns:
        `n_disponibles`, `n_medidas`, `sin_medicion`, `mediana_ms`, `p95_ms`
        (rango más cercano), `max_ms`, `pct_le_50ms` (sobre las medidas),
        `umbral_ms` y `cumple` (p95 ≤ 50 ms). Sin medidas, los valores son
        None: nunca NaN ni 0.
    """
    medidas = sorted(x for x in latencias_disponibles_ms if x is not None)
    resultado: dict[str, Any] = {
        "n_disponibles": len(latencias_disponibles_ms),
        "n_medidas": len(medidas),
        "sin_medicion": len(latencias_disponibles_ms) - len(medidas),
        "mediana_ms": None,
        "p95_ms": None,
        "max_ms": None,
        "pct_le_50ms": None,
        "umbral_ms": UMBRAL_INFERENCIA_MS,
        "cumple": None,
    }
    if not medidas:
        return resultado
    mitad = len(medidas) // 2
    if len(medidas) % 2:
        mediana = medidas[mitad]
    else:
        mediana = (medidas[mitad - 1] + medidas[mitad]) / 2
    p95 = _percentil_nearest_rank(medidas, 95)
    dentro = sum(1 for x in medidas if x <= UMBRAL_INFERENCIA_MS)
    resultado.update(
        mediana_ms=mediana,
        p95_ms=p95,
        max_ms=medidas[-1],
        pct_le_50ms=round(100 * dentro / len(medidas), 2),
        cumple=p95 <= UMBRAL_INFERENCIA_MS,
    )
    return resultado


def resumir_validacion(lineas: Sequence[LineaEvidencia]) -> dict[str, Any]:
    """Métricas de un grupo de revisiones de una misma validación.

    Args:
        lineas: líneas de evidencia (`construir_linea`) de V1 o de V2.

    Returns:
        `n_revisiones`, `disponibles`, `no_disponibles` (con `por_motivo`),
        `latencia`, `latencia_inferencia`, `kappa`, `concordancia` y
        `matriz_confusion`. κ,
        concordancia y matriz usan solo las revisiones disponibles y no
        anuladas.
    """
    disponibles = [x for x in lineas if x.disponible]
    no_disponibles = [x for x in lineas if not x.disponible]
    por_motivo = {m: 0 for m in MOTIVOS_NO_DISPONIBLE}
    for x in no_disponibles:
        por_motivo[x.motivo] = por_motivo.get(x.motivo, 0) + 1

    comparables = [
        x for x in disponibles
        if x.decision != "anular" and x.clase_final_arbitro is not None
    ]
    sistema = [x.clase_sugerida for x in comparables]
    arbitro = [x.clase_final_arbitro for x in comparables]
    coinciden = sum(1 for s, a in zip(sistema, arbitro) if s == a)
    pct = round(100 * coinciden / len(comparables), 2) if comparables else None

    return {
        "n_revisiones": len(lineas),
        "disponibles": len(disponibles),
        "no_disponibles": {"n": len(no_disponibles), "por_motivo": por_motivo},
        "latencia": resumen_latencia(
            [x.latencia_ms for x in disponibles], len(no_disponibles)
        ),
        "latencia_inferencia": resumen_latencia_inferencia(
            [x.latencia_inferencia_ms for x in disponibles]
        ),
        "kappa": cohen_kappa(sistema, arbitro),
        "concordancia": {
            "n": len(comparables),
            "pct": pct,
        },
        "matriz_confusion": matriz_confusion(sistema, arbitro),
    }
