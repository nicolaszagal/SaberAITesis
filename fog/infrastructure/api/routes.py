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
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from fog.application.forward_verdict import ForwardVerdictToClient
from fog.application.process_match import ProcessIncomingMatch
from fog.composition import Container
from fog.domain.models import LuzSignal, MotivoNoDisponible, WeaponSide
from fog.infrastructure.api.schemas import (
    ClipUploadResponse,
    LuzAck,
    LuzRequest,
    MatchConfigRequest,
    MatchConfigResponse,
    OfferRequest,
    OfferResponse,
)
from fog.infrastructure.clips.clip_file_reader import (
    ClipTooLargeError,
    InvalidClipError,
    process_uploaded_clip,
)
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
    session = sessions.get_or_create_default(match_id)
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
        "no, se asume 'right'/'right'. Si la extracción de features falla "
        "(pose incompleta: sin lock A/B o clip muy corto), responde de "
        "inmediato con disponible=false y motivo='pose_incompleta', sin "
        "esperar a Cloud (DEF-08). Si el archivo no abre como video o tiene "
        "menos de MIN_FRAMES frames, responde 400; si supera CLIP_MAX_MB, "
        "responde 413 (DEF-13)."
    ),
)
@inject
async def upload_clip(
    match_id: str,
    file: UploadFile = File(..., description="Clip de video del combate (mismo contenido que el front enviaría por WebRTC)."),
    has_luz_A: bool | None = Form(
        None, description="True si se encendió la luz Favero del tirador A."
    ),
    has_luz_B: bool | None = Form(
        None, description="True si se encendió la luz Favero del tirador B."
    ),
    t_tocado_ms: int | None = Form(
        None, ge=0, description="Instante del tocado en ms desde el inicio del clip (RF-02). Opcional."
    ),
    luz_frame_a: int | None = Form(
        None,
        description=(
            "[OBSOLETO] Alias de has_luz_A: índice de frame (0-based) en que "
            "se prendió la luz Favero de A. Se usa solo si has_luz_A/has_luz_B "
            "se omiten ambos. Preferir has_luz_A."
        ),
    ),
    luz_frame_b: int | None = Form(
        None,
        description=(
            "[OBSOLETO] Alias de has_luz_B: índice de frame (0-based) en que "
            "se prendió la luz Favero de B. Se usa solo si has_luz_A/has_luz_B "
            "se omiten ambos. Preferir has_luz_B."
        ),
    ),
    sessions: SessionRegistry = Depends(Provide[Container.sessions]),
    pose_estimator: PoseEstimatorPort = Depends(Provide[Container.pose_estimator]),
    process_match: ProcessIncomingMatch = Depends(Provide[Container.process_match]),
    forward_verdict: ForwardVerdictToClient = Depends(Provide[Container.forward_verdict]),
    executor: Executor = Depends(Provide[Container.executor]),
    verdict_timeout_s: float = Depends(Provide[Container.config.clip_upload_verdict_timeout_s]),
    clip_max_mb: float = Depends(Provide[Container.config.clip_max_mb]),
    min_frames: int = Depends(Provide[Container.config.min_frames]),
) -> ClipUploadResponse:
    session = sessions.get_or_create_default(match_id)

    try:
        tracked = await process_uploaded_clip(
            file, pose_estimator, executor, clip_max_mb=clip_max_mb, min_frames=min_frames
        )
    except ClipTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except InvalidClipError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # has_luz_A/has_luz_B (bool) es la forma vigente (DEF-14); luz_frame_a/b
    # (índice de frame, reducido a booleano) queda como alias obsoleto para
    # clientes viejos, y solo se usa si los campos nuevos vienen ambos vacíos.
    if has_luz_A is None and has_luz_B is None:
        luz = LuzSignal(has_luz_a=luz_frame_a is not None, has_luz_b=luz_frame_b is not None)
    else:
        luz = LuzSignal(has_luz_a=bool(has_luz_A), has_luz_b=bool(has_luz_B))
    session.set_luz(luz)
    session.t_tocado_ms = t_tocado_ms

    unavailable = await process_match.execute(match_id, tracked, session.weapon_side_a, session.weapon_side_b, luz)

    if unavailable is not None:
        # Extracción falló (pose incompleta): no se publicó nada en Redis,
        # así que no tiene sentido esperar a Cloud (DEF-08).
        return ClipUploadResponse(
            match_id=match_id,
            has_luz_A=luz.has_luz_a,
            has_luz_B=luz.has_luz_b,
            timed_out=False,
            disponible=False,
            motivo=unavailable.motivo.value,
        )

    try:
        await asyncio.wait_for(forward_verdict.execute(match_id), timeout=verdict_timeout_s)
    except asyncio.TimeoutError:
        return ClipUploadResponse(
            match_id=match_id,
            has_luz_A=luz.has_luz_a,
            has_luz_B=luz.has_luz_b,
            timed_out=True,
            disponible=False,
            motivo=MotivoNoDisponible.TIMEOUT.value,
        )

    verdict = session.verdict
    return ClipUploadResponse(
        match_id=match_id,
        has_luz_A=luz.has_luz_a,
        has_luz_B=luz.has_luz_b,
        timed_out=False,
        disponible=True,
        motivo=None,
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
    documentado en CONTRATO_API.md y en VerdictMessage/NoDisponibleMessage
    (schemas.py). Envía un único mensaje JSON —veredicto o no_disponible—
    en cuanto el resultado está disponible (DEF-08)."""
    await websocket.accept()
    session = sessions.get_or_create_default(match_id)
    session.ws = websocket

    try:
        if session.verdict is not None:
            # Conexión tardía: el veredicto ya llegó (ForwardVerdictToClient
            # no pudo enviarlo porque session.ws aún no existía). Lo mandamos
            # nosotros, una sola vez.
            await websocket.send_json(session.verdict.to_ws_message())
        elif session.unavailable is not None:
            # Conexión tardía, resultado no disponible (mismo caso que
            # arriba pero desde ProcessIncomingMatch en vez de
            # ForwardVerdictToClient).
            await websocket.send_json(session.unavailable.to_ws_message())
        else:
            # Conexión temprana: session.ws ya quedó asignado arriba, así que
            # cuando el resultado llegue será ForwardVerdictToClient o
            # ProcessIncomingMatch (tareas en segundo plano) quien lo envíe.
            # Aquí solo mantenemos la conexión abierta hasta entonces —
            # enviar también desde aquí duplicaría el mensaje y rompía el
            # socket (RuntimeError: "Cannot call send once a close message
            # has been sent").
            pending = {
                asyncio.ensure_future(session.verdict_event.wait()),
                asyncio.ensure_future(session.unavailable_event.wait()),
            }
            try:
                await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in pending:
                    if not task.done():
                        task.cancel()
    except WebSocketDisconnect:
        pass
