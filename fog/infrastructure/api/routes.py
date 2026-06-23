"""Router HTTP/WebSocket de Fog. Documentado para Swagger (summary,
description, response_model, tags) por pedido explícito de Nicolas. La
resolución de dependencias usa dependency_injector (Provide[...] + @inject,
ver fog/composition.py) — wiring registrado en fog/main.py.
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import Executor

from aiortc import RTCPeerConnection, RTCSessionDescription
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, File, Form, UploadFile, WebSocket, WebSocketDisconnect

from fog.application.forward_verdict import ForwardVerdictToClient
from fog.application.process_match import ProcessIncomingMatch
from fog.composition import Container
from fog.domain.models import LuzSignal, WeaponSide
from fog.infrastructure.api.schemas import (
    ClipUploadResponse,
    LuzAck,
    LuzRequest,
    MatchConfigRequest,
    MatchConfigResponse,
    OfferRequest,
    OfferResponse,
)
from fog.infrastructure.clips.clip_file_reader import process_uploaded_clip
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from fog.infrastructure.webrtc.track_consumer import consume_track
from fog.ports.pose_estimator import PoseEstimatorPort

router = APIRouter()


@router.post(
    "/matches/config",
    response_model=MatchConfigResponse,
    tags=["matches"],
    summary="Configura un combate antes de iniciarlo (genera match_id)",
    description=(
        "Paso previo opcional a POST /webrtc/offer o POST "
        "/matches/{match_id}/clip: fija el lado de arma (diestro/zurdo) de "
        "cada tirador y genera un match_id para que Edge lo reutilice "
        "después. Si Edge no llama a este endpoint, /webrtc/offer sigue "
        "aceptando weapon_side_A/B directamente en su propio body, igual "
        "que hoy."
    ),
)
@inject
async def configure_match(
    body: MatchConfigRequest,
    sessions: SessionRegistry = Depends(Provide[Container.sessions]),
) -> MatchConfigResponse:
    match_id = str(uuid.uuid4())
    sessions.create(
        match_id,
        WeaponSide(body.weapon_side_A),
        WeaponSide(body.weapon_side_B),
    )
    return MatchConfigResponse(
        match_id=match_id,
        weapon_side_A=body.weapon_side_A,
        weapon_side_B=body.weapon_side_B,
    )


@router.post(
    "/webrtc/offer",
    response_model=OfferResponse,
    tags=["webrtc"],
    summary="Inicia un combate vía WebRTC",
    description=(
        "Recibe la oferta SDP de Edge, crea la sesión del combate, arma la "
        "RTCPeerConnection y devuelve la respuesta SDP. Tras esto, Fog "
        "consume la pista de video, extrae features (192-dim, lstm_4class) "
        "y las publica en Redis para Cloud. El veredicto llega luego por "
        "GET /ws/veredicto/{match_id}."
    ),
)
@inject
async def webrtc_offer(
    body: OfferRequest,
    sessions: SessionRegistry = Depends(Provide[Container.sessions]),
    pose_estimator: PoseEstimatorPort = Depends(Provide[Container.pose_estimator]),
    process_match: ProcessIncomingMatch = Depends(Provide[Container.process_match]),
    forward_verdict: ForwardVerdictToClient = Depends(Provide[Container.forward_verdict]),
    executor: Executor = Depends(Provide[Container.executor]),
    luz_timeout_s: float = Depends(Provide[Container.config.luz_timeout_s]),
) -> OfferResponse:
    match_id = body.match_id or str(uuid.uuid4())
    # Get-or-create: si match_id ya fue configurado vía POST /matches/config,
    # se reutiliza esa sesión (con su weapon_side_A/B ya fijado) en vez de
    # pisarla con los campos de este body. Mismo patrón que webrtc_luz y
    # ws_veredicto más abajo.
    session = sessions.get(match_id)
    if session is None:
        session = sessions.create(
            match_id,
            WeaponSide(body.weapon_side_A),
            WeaponSide(body.weapon_side_B),
        )

    pc = RTCPeerConnection()
    session.pc = pc

    @pc.on("track")
    def on_track(track):
        if track.kind == "video":
            asyncio.ensure_future(
                consume_track(track, session, pose_estimator, process_match, executor, luz_timeout_s)
            )

    offer = RTCSessionDescription(sdp=body.sdp, type=body.type)
    await pc.setRemoteDescription(offer)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    asyncio.ensure_future(forward_verdict.execute(match_id))

    return OfferResponse(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type,
        match_id=match_id,
    )


@router.post(
    "/webrtc/{match_id}/luz",
    response_model=LuzAck,
    tags=["webrtc"],
    summary="Reporta la señal de luz Favero de un combate",
    description=(
        "Edge envía este endpoint cuando detecta el cierre de circuito RJ11 "
        "de alguna de las luces Favero. Si no llega antes de que termine el "
        "clip, Fog procesa con luz 'apagada' en ambos lados tras un timeout "
        "(ver shared.config.FAVERO_LUZ_TIMEOUT_S)."
    ),
)
@inject
async def webrtc_luz(
    match_id: str,
    body: LuzRequest,
    sessions: SessionRegistry = Depends(Provide[Container.sessions]),
) -> LuzAck:
    session = sessions.get(match_id)
    if session is None:
        session = sessions.create(match_id, WeaponSide.RIGHT, WeaponSide.RIGHT)
    session.set_luz(LuzSignal(has_luz_a=body.has_luz_A, has_luz_b=body.has_luz_B))
    return LuzAck(match_id=match_id, has_luz_A=body.has_luz_A, has_luz_B=body.has_luz_B)


@router.post(
    "/matches/{match_id}/clip",
    response_model=ClipUploadResponse,
    tags=["matches"],
    summary="Sube un clip completo + frames de señal Favero (sin WebRTC)",
    description=(
        "Alternativa a POST /webrtc/offer para subir un clip ya grabado "
        "(en vez de transmitirlo por WebRTC) junto con los frames en que "
        "se prendió cada luz Favero. Corre el pipeline completo: pose+"
        "tracking frame a frame, extracción de 192 features, publicación "
        "en Redis hacia Cloud, y espera (síncrona, con timeout) el "
        "veredicto antes de responder — a diferencia del flujo WebRTC, "
        "que lo entrega async por WebSocket. Si match_id fue configurado "
        "antes vía POST /matches/config, se usa ese weapon_side_A/B; si "
        "no, se asume 'right'/'right'."
    ),
)
@inject
async def upload_clip(
    match_id: str,
    file: UploadFile = File(..., description="Clip de video del combate (mismo contenido que el front enviaría por WebRTC)."),
    luz_frame_a: int | None = Form(
        None, description="Índice de frame (0-based) en que se prendió la luz Favero de A. Omitir/null si no se prendió."
    ),
    luz_frame_b: int | None = Form(
        None, description="Índice de frame (0-based) en que se prendió la luz Favero de B. Omitir/null si no se prendió."
    ),
    sessions: SessionRegistry = Depends(Provide[Container.sessions]),
    pose_estimator: PoseEstimatorPort = Depends(Provide[Container.pose_estimator]),
    process_match: ProcessIncomingMatch = Depends(Provide[Container.process_match]),
    forward_verdict: ForwardVerdictToClient = Depends(Provide[Container.forward_verdict]),
    executor: Executor = Depends(Provide[Container.executor]),
    verdict_timeout_s: float = Depends(Provide[Container.config.clip_upload_verdict_timeout_s]),
) -> ClipUploadResponse:
    session = sessions.get(match_id)
    if session is None:
        session = sessions.create(match_id, WeaponSide.RIGHT, WeaponSide.RIGHT)

    tracked = await process_uploaded_clip(file, pose_estimator, executor)

    luz = LuzSignal(has_luz_a=luz_frame_a is not None, has_luz_b=luz_frame_b is not None)
    session.set_luz(luz)

    await process_match.execute(match_id, tracked, session.weapon_side_a, session.weapon_side_b, luz)

    try:
        await asyncio.wait_for(forward_verdict.execute(match_id), timeout=verdict_timeout_s)
    except asyncio.TimeoutError:
        return ClipUploadResponse(
            match_id=match_id,
            has_luz_A=luz.has_luz_a,
            has_luz_B=luz.has_luz_b,
            timed_out=True,
        )

    verdict = session.verdict
    return ClipUploadResponse(
        match_id=match_id,
        has_luz_A=luz.has_luz_a,
        has_luz_B=luz.has_luz_b,
        timed_out=False,
        fencer=verdict.fencer if verdict else None,
        action=verdict.action if verdict else None,
        confidence=verdict.confidence if verdict else None,
    )


@router.websocket("/ws/veredicto/{match_id}")
@inject
async def ws_veredicto(
    websocket: WebSocket,
    match_id: str,
    sessions: SessionRegistry = Depends(Provide[Container.sessions]),
):
    """No aparece en Swagger (las rutas WebSocket no son parte de OpenAPI),
    documentado en CONTRATO_API.md y en VerdictMessage (schemas.py). Envía
    un único mensaje JSON con el veredicto en cuanto está disponible."""
    await websocket.accept()
    session = sessions.get(match_id)
    if session is None:
        session = sessions.create(match_id, WeaponSide.RIGHT, WeaponSide.RIGHT)
    session.ws = websocket

    try:
        if session.verdict is not None:
            # Conexión tardía: el veredicto ya llegó (ForwardVerdictToClient
            # no pudo enviarlo porque session.ws aún no existía). Lo mandamos
            # nosotros, una sola vez.
            verdict = session.verdict
            await websocket.send_json({
                "type": "veredicto",
                "match_id": verdict.match_id,
                "fencer": verdict.fencer,
                "action": verdict.action,
                "confidence": verdict.confidence,
            })
        else:
            # Conexión temprana: session.ws ya quedó asignado arriba, así que
            # cuando el veredicto llegue será fog.application.forward_verdict.
            # ForwardVerdictToClient (tarea en segundo plano lanzada desde
            # POST /webrtc/offer) quien lo envíe. Aquí solo mantenemos la
            # conexión abierta hasta entonces — enviar también desde aquí
            # duplicaría el mensaje y rompía el socket (RuntimeError:
            # "Cannot call send once a close message has been sent").
            await session.verdict_event.wait()
    except WebSocketDisconnect:
        pass
