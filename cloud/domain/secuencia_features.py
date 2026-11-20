"""Validación del contrato de features (CONTRATO_API.md, sección 5).

Es la única definición de qué es una secuencia de features válida: la usan los dos
adaptadores de entrada de Cloud (el consumidor de Redis y la API HTTP), de modo que
ninguno duplica las reglas.
"""

from __future__ import annotations

import numpy as np

from cloud.domain.models import FeatureSequence, LuzSignal

# "T,192": T = frames reales del clip, 192 = features por frame (A+B).
DIMENSION_FEATURES = 192
DTYPE_ESPERADO = "float32"


class ContratoInvalidoError(ValueError):
    """Una secuencia de features no respeta el contrato."""


def construir_secuencia(
    *,
    match_id: str,
    revision_id: str,
    shape: str,
    dtype: str,
    buffer: bytes,
    luz: LuzSignal,
    weapon_side_a: str,
    weapon_side_b: str,
) -> FeatureSequence:
    """Valida los campos de una entrada y arma la `FeatureSequence`.

    Args:
        match_id: id del combate.
        revision_id: id de la revisión (obligatorio y no vacío).
        shape: texto `"T,192"`.
        dtype: debe ser `"float32"`.
        buffer: bytes de `array.tobytes()`, con `T * 192 * 4` bytes.
        luz: señal de luz Favero del clip.
        weapon_side_a: brazo armado de A, reenviado tal cual.
        weapon_side_b: brazo armado de B, reenviado tal cual.

    Returns:
        La secuencia `(T, 192)` lista para el clasificador.

    Raises:
        ContratoInvalidoError: si `dtype`, `shape` o el tamaño del buffer no respetan el
            contrato, o si falta el id de la revisión.
    """
    if not revision_id:
        raise ContratoInvalidoError("revision_id vacío")
    if dtype != DTYPE_ESPERADO:
        raise ContratoInvalidoError(f"dtype inesperado: '{dtype}' (se espera '{DTYPE_ESPERADO}')")
    try:
        forma = tuple(int(v) for v in shape.split(","))
    except ValueError:
        raise ContratoInvalidoError(f"shape inválido: {shape!r}") from None
    if len(forma) != 2 or forma[0] < 1 or forma[1] != DIMENSION_FEATURES:
        raise ContratoInvalidoError(
            f"shape inesperado: {forma} (se espera (T>=1, {DIMENSION_FEATURES}))"
        )
    esperado = forma[0] * forma[1] * np.dtype(dtype).itemsize
    if len(buffer) != esperado:
        raise ContratoInvalidoError(
            f"tamaño de buffer ({len(buffer)} bytes) no coincide con shape {forma} "
            f"y dtype '{dtype}' (esperado {esperado} bytes)"
        )
    return FeatureSequence(
        match_id=match_id,
        revision_id=revision_id,
        sequence=np.frombuffer(buffer, dtype=dtype).reshape(forma),
        luz=luz,
        weapon_side_a=weapon_side_a,
        weapon_side_b=weapon_side_b,
    )
