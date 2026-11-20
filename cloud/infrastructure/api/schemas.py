"""Esquemas de POST /v1/clasificar (CONTRATO_API.md, sección 5.1).

Los campos replican los de `fog:features`; `features` viaja en base64 y las luces como booleanos.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SolicitudClasificar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str = Field(min_length=1, max_length=64)
    revision_id: str = Field(min_length=1, max_length=64)
    shape: str = Field(max_length=32, description='Texto "T,192".')
    dtype: str = Field(max_length=16, description='Siempre "float32".')
    features: str = Field(description="`array.tobytes()` de la secuencia (T,192), en base64.")
    has_luz_A: bool = False
    has_luz_B: bool = False
    weapon_side_A: str = Field(max_length=16)
    weapon_side_B: str = Field(max_length=16)


class RespuestaClasificar(BaseModel):
    match_id: str | None
    revision_id: str
    disponible: bool
    action_class: str | None = None
    confidence: float | None = None
    fencer: str | None = None
    probs: dict[str, float] | None = None
    latencia_inferencia_ms: int | None = None
    modelo: str | None = None
    atencion: list[float] | None = None
    motivo_no_disp: str | None = None
