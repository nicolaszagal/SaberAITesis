"""Esquemas Pydantic de la API de Fog — usados como response_model/body en
infrastructure/api/routes.py para que Swagger (/docs) documente forma y
ejemplos de cada endpoint (ver CONTRATO_API.md).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OfferRequest(BaseModel):
    sdp: str = Field(..., description="SDP de la oferta WebRTC generada por Edge.")
    type: str = Field(..., description="Tipo de mensaje SDP, normalmente 'offer'.")
    match_id: str | None = Field(
        None, description="ID del combate. Si se omite, Fog genera uno nuevo (uuid4)."
    )
    weapon_side_A: str = Field(
        "right", description="Lado del arma del tirador A: 'right' o 'left'."
    )
    weapon_side_B: str = Field(
        "right", description="Lado del arma del tirador B: 'right' o 'left'."
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


class LuzRequest(BaseModel):
    has_luz_A: bool = Field(..., description="True si la luz Favero del tirador A se encendió.")
    has_luz_B: bool = Field(..., description="True si la luz Favero del tirador B se encendió.")


class LuzAck(BaseModel):
    match_id: str
    has_luz_A: bool
    has_luz_B: bool


class MatchConfigRequest(BaseModel):
    """Paso previo opcional a POST /webrtc/offer (o a POST
    /matches/{match_id}/clip): genera un match_id y fija el lado de arma
    de cada tirador antes de que llegue el video. Si Edge no llama a este
    endpoint, /webrtc/offer sigue aceptando weapon_side_A/B directamente
    en su propio body, igual que hoy (no es un campo obligatorio)."""

    weapon_side_A: str = Field(
        "right", description="Lado del arma del tirador A: 'right' o 'left'."
    )
    weapon_side_B: str = Field(
        "right", description="Lado del arma del tirador B: 'right' o 'left'."
    )


class MatchConfigResponse(BaseModel):
    match_id: str = Field(..., description="ID de combate generado (uuid4), a reutilizar en /webrtc/offer o /matches/{match_id}/clip.")
    weapon_side_A: str
    weapon_side_B: str


class ClipUploadResponse(BaseModel):
    """Respuesta de POST /matches/{match_id}/clip. A diferencia del flujo
    WebRTC (veredicto async por WebSocket), este endpoint corre el
    pipeline completo (pose+features+Redis+Cloud) y espera el veredicto
    de forma síncrona antes de responder, hasta
    shared.config.CLIP_UPLOAD_VERDICT_TIMEOUT_S."""

    match_id: str
    has_luz_A: bool = Field(..., description="True si se envió luz_frame_a (no None).")
    has_luz_B: bool = Field(..., description="True si se envió luz_frame_b (no None).")
    timed_out: bool = Field(
        ..., description="True si Cloud no publicó veredicto dentro del timeout configurado."
    )
    fencer: str | None = Field(None, description="'ROJ' o 'VER'. None si timed_out=True.")
    action: str | None = Field(None, description="Clase de acción. None si timed_out=True.")
    confidence: float | None = Field(None, description="Confianza 0-1. None si timed_out=True.")


class VerdictMessage(BaseModel):
    """Forma del mensaje que Fog envía por el WebSocket
    GET /ws/veredicto/{match_id}. No es un endpoint REST — se documenta
    aquí solo como referencia de contrato para Swagger/lectores del código."""

    type: str = Field("veredicto", description="Siempre 'veredicto'.")
    match_id: str
    fencer: str = Field(..., description="'ROJ' o 'VER', ver shared.config.FENCER_COLOR.")
    action: str = Field(..., description="Clase de acción: AttackA, AttackB, ResponseA o ResponseB.")
    confidence: float = Field(..., description="Confianza softmax de la clase ganadora, 0-1.")
