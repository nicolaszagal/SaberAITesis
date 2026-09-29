"""Esquemas Pydantic de la API de Fog — usados como response_model/body en
infrastructure/api/routes.py para que Swagger (/docs) documente forma y
ejemplos de cada endpoint (ver CONTRATO_API.md).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

WeaponSideLiteral = Literal["right", "left"]
# Taxonomía única de la API: los nombres del modelo (D-06). Coincide con
# fog.domain.models.CLASES_MODELO; la traducción al esquema vive en los
# adaptadores de persistencia.
ClaseFinalLiteral = Literal[
    "AttackA", "AttackB", "ContrattackA", "ContrattackB", "RiposteA", "RiposteB"
]


class OfferRequest(BaseModel):
    sdp: str = Field(..., description="SDP de la oferta WebRTC generada por Edge.")
    type: str = Field(..., description="Tipo de mensaje SDP, normalmente 'offer'.")
    match_id: str | None = Field(
        None, description="ID del combate. Si se omite, Fog genera uno nuevo (uuid4)."
    )
    weapon_side_A: WeaponSideLiteral = Field(
        ..., description="Brazo armado del tirador A: 'right' o 'left'. Obligatorio, sin valor por defecto."
    )
    weapon_side_B: WeaponSideLiteral = Field(
        ..., description="Brazo armado del tirador B: 'right' o 'left'. Obligatorio, sin valor por defecto."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "sdp": "v=0\r\no=- ...",
                "type": "offer",
                "match_id": None,
                "weapon_side_A": "right",
                "weapon_side_B": "left",
            }
        }
    }


class OfferResponse(BaseModel):
    sdp: str = Field(..., description="SDP de la respuesta generada por Fog.")
    type: str = Field(..., description="Tipo de mensaje SDP, normalmente 'answer'.")
    match_id: str = Field(..., description="ID del combate, generado por Fog si no se envió uno.")
    revision_id: str = Field(
        ...,
        description=(
            "Identifica la sesión: es el que se usa en GET /ws/veredicto/{revision_id}. "
            "Este flujo no abre `revision_var`, así que no es una fila de la base."
        ),
    )


class LuzRequest(BaseModel):
    has_luz_A: bool = Field(..., description="True si la luz Favero del tirador A se encendió.")
    has_luz_B: bool = Field(..., description="True si la luz Favero del tirador B se encendió.")


class LuzAck(BaseModel):
    match_id: str
    has_luz_A: bool
    has_luz_B: bool


class MatchConfigRequest(BaseModel):
    """CU-01 (F-039, RF-07): configura el combate. Crea los dos tiradores y
    el combate en la base y devuelve el `match_id` (= id del combate) que
    Edge reutiliza en /webrtc/offer, /matches/{match_id}/clip y
    /webrtc/{match_id}/luz. El veredicto y el WebSocket usan el
    `revision_id` de cada clip."""

    evento_id: uuid.UUID = Field(..., description="Evento existente (`sabre.evento`) al que pertenece el combate.")
    pista: str = Field(..., min_length=1, description="Pista asignada al combate.")
    arbitro_id: uuid.UUID = Field(
        ..., description="Usuario árbitro existente (`sabre.usuario`). Queda también como `configurado_por`."
    )

    alias_A: str = Field(..., min_length=1, description="Alias del tirador A (minimización de datos).")
    weapon_side_A: WeaponSideLiteral = Field(
        ..., description="Brazo armado del tirador A: 'right' (diestro) o 'left' (zurdo). Obligatorio."
    )
    es_menor_A: bool = Field(..., description="True si el tirador A es menor de edad.")
    consentimiento_firmado_A: bool = Field(False, description="Consentimiento informado firmado (RNF-16).")
    consentimiento_fecha_A: date | None = Field(None, description="Fecha del consentimiento; obligatoria si está firmado.")
    firmante_A: str | None = Field(None, description="Apoderado que firma; obligatorio si es menor y hay consentimiento.")

    alias_B: str = Field(..., min_length=1, description="Alias del tirador B.")
    weapon_side_B: WeaponSideLiteral = Field(
        ..., description="Brazo armado del tirador B: 'right' (diestro) o 'left' (zurdo). Obligatorio."
    )
    es_menor_B: bool = Field(..., description="True si el tirador B es menor de edad.")
    consentimiento_firmado_B: bool = Field(False, description="Consentimiento informado firmado (RNF-16).")
    consentimiento_fecha_B: date | None = Field(None, description="Fecha del consentimiento; obligatoria si está firmado.")
    firmante_B: str | None = Field(None, description="Apoderado que firma; obligatorio si es menor y hay consentimiento.")

    @model_validator(mode="after")
    def _consentimiento_coherente(self) -> "MatchConfigRequest":
        # Mismas restricciones CHECK de `sabre.tirador`, para responder 422 y no 500.
        for lado in ("A", "B"):
            firmado = getattr(self, f"consentimiento_firmado_{lado}")
            if firmado and getattr(self, f"consentimiento_fecha_{lado}") is None:
                raise ValueError(f"consentimiento_fecha_{lado} es obligatoria si consentimiento_firmado_{lado}")
            if firmado and getattr(self, f"es_menor_{lado}") and not getattr(self, f"firmante_{lado}"):
                raise ValueError(f"firmante_{lado} es obligatorio si el tirador {lado} es menor y firmó")
        return self


class MatchConfigResponse(BaseModel):
    match_id: str = Field(..., description="Id del combate creado (uuid), a reutilizar en el resto de la API.")
    weapon_side_A: WeaponSideLiteral
    weapon_side_B: WeaponSideLiteral


class VeredictoRequest(BaseModel):
    """CU-10 (F-033, RF-20): decisión final del árbitro sobre una revisión
    (POST /revisiones/{revision_id}/veredicto). El sistema solo sugiere (RNF-01)."""

    decision: Literal["mantener", "cambiar", "anular"] = Field(
        ...,
        description=(
            "Relación con la decisión original del árbitro en pista: 'mantener' la acción, "
            "'cambiar' la acción o 'anular' (acción simultánea, t.106)."
        ),
    )
    clase_final: ClaseFinalLiteral | None = Field(
        None,
        description=(
            "Decisión final declarada por el árbitro, siempre. Obligatoria con 'mantener' y "
            "'cambiar' (también si la clasificación no estuvo disponible); no se admite con "
            "'anular'. Valores de la taxonomía del modelo."
        ),
    )
    arbitro_id: uuid.UUID = Field(..., description="Usuario árbitro existente que decide.")

    @model_validator(mode="after")
    def _clase_final_coherente(self) -> "VeredictoRequest":
        if self.decision in ("mantener", "cambiar") and self.clase_final is None:
            raise ValueError(f"clase_final es obligatoria cuando decision='{self.decision}'")
        if self.decision == "anular" and self.clase_final is not None:
            raise ValueError("clase_final no se admite cuando decision='anular'")
        return self


class VeredictoResponse(BaseModel):
    match_id: str
    revision_id: uuid.UUID
    veredicto_id: uuid.UUID
    decision: Literal["mantener", "cambiar", "anular"]
    clase_final: ClaseFinalLiteral | None
    arbitro_id: uuid.UUID
    registrado_en: datetime
    cerrada_en: datetime = Field(..., description="Cierre de la revisión (igual a registrado_en).")
    auditoria_seq: int = Field(..., description="Posición del registro en la cadena de auditoría.")
    auditoria_hash: str = Field(..., description="SHA-256 encadenado del registro (RNF-05).")


class ClipUploadResponse(BaseModel):
    """Respuesta de POST /matches/{match_id}/clip. A diferencia del flujo
    WebRTC (veredicto async por WebSocket), este endpoint corre el
    pipeline completo (pose+features+Redis+Cloud) y espera el veredicto
    de forma síncrona antes de responder, hasta
    shared.config.CLIP_UPLOAD_VERDICT_TIMEOUT_S.

    `disponible=False` cubre dos casos distintos (DEF-08): si Fog no pudo
    extraer features válidas (pose incompleta), responde de inmediato con
    `motivo="pose_incompleta"` y `timed_out=False` — nunca llegó a
    publicar en Redis, así que no tiene sentido esperar a Cloud. Si Fog sí
    publicó pero Cloud no respondió dentro del timeout, responde con
    `timed_out=True` y `motivo="timeout"`."""

    match_id: str
    revision_id: str = Field(
        ...,
        description=(
            "Revisión abierta por este clip. Es el identificador de "
            "POST /revisiones/{revision_id}/veredicto y de GET /ws/veredicto/{revision_id}."
        ),
    )
    has_luz_A: bool = Field(..., description="True si se recibió la luz Favero del tirador A (`has_luz_A` o, como alias obsoleto, `luz_frame_a`).")
    has_luz_B: bool = Field(..., description="True si se recibió la luz Favero del tirador B (`has_luz_B` o, como alias obsoleto, `luz_frame_b`).")
    timed_out: bool = Field(
        ...,
        description=(
            "True solo si Fog publicó features en Redis y Cloud no "
            "respondió dentro del timeout configurado (motivo='timeout')."
        ),
    )
    disponible: bool = Field(
        ..., description="False si la clasificación no está disponible (ver `motivo`)."
    )
    motivo: str | None = Field(
        None,
        description=(
            "Motivo cuando disponible=False, uno de "
            "clasificacion.motivo_no_disp (sabre_ai_schema.sql): "
            "'pose_incompleta', 'confianza_baja', 'clase_fuera_mvp', "
            "'timeout', 'sin_senal_favero', 'mensaje_invalido'. None si disponible=True."
        ),
    )
    fencer: str | None = Field(None, description="'ROJ' o 'VER'. None si disponible=False.")
    action: str | None = Field(None, description="Clase de acción. None si disponible=False.")
    confidence: float | None = Field(None, description="Confianza 0-1. None si disponible=False.")


class VerdictMessage(BaseModel):
    """Forma del mensaje que Fog envía por el WebSocket
    GET /ws/veredicto/{revision_id}. No es un endpoint REST — se documenta
    aquí solo como referencia de contrato para Swagger/lectores del código."""

    type: str = Field("veredicto", description="Siempre 'veredicto'.")
    match_id: str
    revision_id: str
    fencer: str = Field(..., description="'ROJ' o 'VER', ver shared.config.FENCER_COLOR.")
    action: str = Field(
        ...,
        description=(
            "Clase de acción: AttackA, AttackB, ContrattackA, ContrattackB, "
            "RiposteA o RiposteB."
        ),
    )
    confidence: float = Field(..., description="Confianza softmax de la clase ganadora, 0-1.")


class NoDisponibleMessage(BaseModel):
    """Forma del mensaje que Fog envía por el WebSocket
    GET /ws/veredicto/{revision_id} cuando la clasificación no está
    disponible (DEF-08). No es un endpoint REST — se documenta aquí solo
    como referencia de contrato para Swagger/lectores del código."""

    type: str = Field("no_disponible", description="Siempre 'no_disponible'.")
    match_id: str
    revision_id: str
    motivo: str = Field(
        ...,
        description=(
            "Uno de clasificacion.motivo_no_disp (sabre_ai_schema.sql): "
            "'pose_incompleta', 'confianza_baja', 'clase_fuera_mvp', "
            "'timeout', 'sin_senal_favero'."
        ),
    )
