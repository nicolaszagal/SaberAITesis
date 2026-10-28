"""Resumen descriptivo del razonamiento sobre un conjunto de clips (EXP03-b).

Dominio puro. Sirve para comparar, con la misma tabla, una muestra de clips de
entrenamiento con las revisiones de la Validación 1. Es un análisis
descriptivo, no una métrica de aceptación.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field

from fog.domain.razonamiento import (
    DISCORDANTE,
    INSUFICIENTE,
    MOTIVO_DETECCION,
    MOTIVO_SIN_SUBIDA,
    NO_CONCLUYENTE,
    RESPALDADA,
    Razonamiento,
)

ESTADOS = (RESPALDADA, DISCORDANTE, NO_CONCLUYENTE, INSUFICIENTE)
CAUSAS = (MOTIVO_SIN_SUBIDA, MOTIVO_DETECCION)
# (etiqueta, desde, hasta) de `lock_frame`; -1 es "sin lock".
TRAMOS_LOCK = (("0", 0, 0), ("1 a 5", 1, 5), ("6 a 15", 6, 15), ("16 o más", 16, 10**9))


@dataclass(frozen=True)
class ClipAnalizado:
    """Resultado del razonamiento de un clip, sin las frases.

    Attributes:
        clip: identificador del clip o de la revisión.
        clase: clase sugerida (vocabulario del modelo).
        estado: estado del razonamiento.
        causa: con `insuficiente`, por qué falta la extensión de un tirador.
        u1_censurados: tiradores cuyo inicio de extensión quedó censurado.
        u2: None si no hubo inicio de desplazamiento; si lo hubo, si quedó censurado.
        lock_frame: frame del clip al que corresponde el índice 0 (-1 si no hubo lock).
    """

    clip: str
    clase: str
    estado: str
    causa: str | None
    u1_censurados: tuple[str, ...]
    u2: bool | None
    lock_frame: int


@dataclass(frozen=True)
class ResumenMuestra:
    """Tabla de resumen de una muestra de clips."""

    n: int
    estados: dict[str, int]
    causas_insuficiente: dict[str, int]
    u1_clips_con_censura: int
    u1_clips_ambos_censurados: int
    u2_con_inicio: int
    u2_censurados: int
    lock_tramos: dict[str, int]
    lock_min: int | None = None
    lock_mediana: float | None = None
    lock_max: int | None = None
    extra: dict = field(default_factory=dict)


def analizar_clip(
    clip: str, clase: str, razonamiento: Razonamiento, lock_frame: int
) -> ClipAnalizado:
    """Reduce un `Razonamiento` a lo que cuenta la tabla de resumen.

    Args:
        clip: identificador del clip o de la revisión.
        clase: clase sugerida (vocabulario del modelo).
        razonamiento: resultado de `construir_razonamiento`.
        lock_frame: frame del índice 0 del clip (-1 si no hubo lock).

    Returns:
        El clip analizado.
    """
    eventos = razonamiento.eventos
    causa = None
    if razonamiento.estado == INSUFICIENTE:
        z = next(t for t in ("A", "B") if eventos.extension[t] is None)
        causa = eventos.faltantes[z]
    d = eventos.desplazamiento
    return ClipAnalizado(
        clip=clip,
        clase=clase,
        estado=razonamiento.estado,
        causa=causa,
        u1_censurados=tuple(
            t for t in ("A", "B")
            if (e := eventos.extension[t]) is not None and e.censurado_inicio
        ),
        u2=None if d is None else d.censurado_inicio,
        lock_frame=lock_frame,
    )


def resumir(clips: list[ClipAnalizado]) -> ResumenMuestra:
    """Cuenta estados, causas, censuras de U1 y U2 y la distribución de `lock_frame`.

    Args:
        clips: clips analizados.

    Returns:
        La tabla de resumen (con ceros si `clips` está vacío).
    """
    estados = Counter(c.estado for c in clips)
    causas = Counter(c.causa for c in clips if c.causa)
    tramos = {etiqueta: 0 for etiqueta, _, _ in TRAMOS_LOCK}
    tramos["sin lock (-1)"] = 0
    locks = [c.lock_frame for c in clips if c.lock_frame >= 0]
    for c in clips:
        if c.lock_frame < 0:
            tramos["sin lock (-1)"] += 1
            continue
        for etiqueta, desde, hasta in TRAMOS_LOCK:
            if desde <= c.lock_frame <= hasta:
                tramos[etiqueta] += 1
    con_u2 = [c for c in clips if c.u2 is not None]
    return ResumenMuestra(
        n=len(clips),
        estados={e: estados.get(e, 0) for e in ESTADOS},
        causas_insuficiente={k: causas.get(k, 0) for k in CAUSAS},
        u1_clips_con_censura=sum(1 for c in clips if c.u1_censurados),
        u1_clips_ambos_censurados=sum(1 for c in clips if len(c.u1_censurados) == 2),
        u2_con_inicio=len(con_u2),
        u2_censurados=sum(1 for c in con_u2 if c.u2),
        lock_tramos=tramos,
        lock_min=min(locks) if locks else None,
        lock_mediana=statistics.median(locks) if locks else None,
        lock_max=max(locks) if locks else None,
    )
