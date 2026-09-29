"""Router HTTP/WebSocket de Fog. Documentado para Swagger (summary,
description, response_model, tags) por pedido explícito de Nicolas. La
resolución de dependencias usa dependency_injector (Provide[...] + @inject,
ver fog/composition.py) — wiring registrado en fog/main.py.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import Executor

from aiortc import RTCPeerConnection, RTCSessionDescription
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from fog.application.abrir_revision import AbrirRevisionVar, VideoGuardado
from fog.application.configurar_combate import ConfigurarCombate, DatosTirador
from fog.application.forward_verdict import ForwardVerdictToClient
from fog.application.process_match import ProcessIncomingMatch
from fog.application.registrar_clasificacion import RegistrarClasificacion
from fog.application.registrar_veredicto import RegistrarVeredicto
from fog.composition import Container
from fog.domain.audit_models import Combate
from fog.domain.errors import (
    ClasificacionPendiente,
    RecursoNoEncontrado,
    SinModeloActivo,
    VeredictoInvalido,
    VeredictoYaRegistrado,
)
from fog.domain.models import (
    LuzSignal,
    MotivoNoDisponible,
    UnavailableResult,
    VerdictView,
    WeaponSide,
    lado_de_brazo,
)
from fog.infrastructure.api.schemas import (
    ClipUploadResponse,
    LuzAck,
    LuzRequest,
    MatchConfigRequest,
    MatchConfigResponse,
    OfferRequest,
    OfferResponse,
    VeredictoRequest,
    VeredictoResponse,
)
from fog.infrastructure.clips.clip_file_reader import (
    ClipTooLargeError,
    InvalidClipError,
    process_uploaded_clip,
)
from fog.infrastructure.webrtc.session_registry import SessionRegistry
from fog.infrastructure.webrtc.track_consumer import consume_track
from fog.ports.file_storage import FileStoragePort
from fog.ports.pose_estimator import PoseEstimatorPort
from fog.ports.unidad_de_trabajo import UnidadDeTrabajoPort

router = APIRouter()


async def _combate_o_none(match_id: str, uow: UnidadDeTrabajoPort) -> Combate | None:
    """Busca en la base el combate que corresponde a `match_id` (= id del combate)."""
    try:
        combate_id = uuid.UUID(match_id)
    except ValueError:
        return None
    async with uow.transaccion() as tx:
        return await tx.combates.obtener(combate_id)


def _combate_no_creado(match_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"el combate {match_id!r} no fue creado (POST /matches/config)",
    )


@router.post(
    "/matches/config",
    response_model=MatchConfigResponse,
    tags=["matches"],
    summary="Configura un combate (CU-01) y genera match_id",
    description=(
        "Crea en una transacción los dos tiradores (por alias) y el combate, "
        "con el brazo armado de cada uno (right → diestro, left → zurdo). "
        "El brazo armado es obligatorio, sin valor por defecto (RF-07): sin "
        "él responde 422 y no crea nada. `evento_id` y `arbitro_id` deben "
        "existir (404 si no). El `match_id` devuelto es el id del combate y "
        "es el que exigen /matches/{match_id}/clip y /webrtc/{match_id}/luz. "
        "Un combate admite N revisiones (una por clip): el veredicto y el "
        "WebSocket se identifican por el `revision_id` que devuelve cada clip."
    ),
    responses={404: {"description": "El evento o el árbitro no existen."}},
)
@inject
async def configure_match(
    body: MatchConfigRequest,
    configurar_combate: ConfigurarCombate = Depends(Provide[Container.configurar_combate]),
) -> MatchConfigResponse:
    try:
        combate = await configurar_combate.execute(
            evento_id=body.evento_id,
            pista=body.pista,
            arbitro_id=body.arbitro_id,
            tirador_a=DatosTirador(
                alias=body.alias_A,
                weapon_side=WeaponSide(body.weapon_side_A),
                es_menor=body.es_menor_A,
                consentimiento_firmado=body.consentimiento_firmado_A,
                consentimiento_fecha=body.consentimiento_fecha_A,
                firmante=body.firmante_A,
            ),
            tirador_b=DatosTirador(
                alias=body.alias_B,
                weapon_side=WeaponSide(body.weapon_side_B),
                es_menor=body.es_menor_B,
                consentimiento_firmado=body.consentimiento_firmado_B,
                consentimiento_fecha=body.consentimiento_fecha_B,
                firmante=body.firmante_B,
            ),
        )
    except RecursoNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=f"no existe: {exc}") from exc
    return MatchConfigResponse(
        match_id=str(combate.id),
        weapon_side_A=body.weapon_side_A,
        weapon_side_B=body.weapon_side_B,
    )


@router.post(
    "/webrtc/offer",
    response_model=OfferResponse,
    tags=["webrtc"],
    summary="Inicia un combate vía WebRTC",
    description=(
        "Recibe la oferta SDP de Edge, crea la sesión del combate (con "
        "weapon_side_A/B obligatorios, sin valor por defecto), arma la "
        "RTCPeerConnection y devuelve la respuesta SDP junto con el "
        "`revision_id` de la sesión (un `uuid` que este flujo genera y no "
        "persiste en la base). Tras esto, Fog consume la pista de video, "
        "extrae features (192-dim) y las publica en Redis para Cloud. El "
        "veredicto llega luego por GET /ws/veredicto/{revision_id}."
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
    uow: UnidadDeTrabajoPort = Depends(Provide[Container.unidad_de_trabajo]),
    luz_timeout_s: float = Depends(Provide[Container.config.luz_timeout_s]),
) -> OfferResponse:
    match_id = body.match_id or str(uuid.uuid4())
    # Si match_id ya fue configurado vía POST /matches/config, se usa el
    # brazo armado guardado en el combate en vez de los campos de este body;
    # si no, este body fija el brazo armado de la sesión.
    combate = await _combate_o_none(match_id, uow)
    if combate is not None:
        weapon_side_a, weapon_side_b = lado_de_brazo(combate.brazo_a), lado_de_brazo(combate.brazo_b)
    else:
        weapon_side_a, weapon_side_b = WeaponSide(body.weapon_side_A), WeaponSide(body.weapon_side_B)
    # Este flujo no abre `revision_var`: el revision_id solo identifica la
    # sesión (stream de veredicto y WebSocket).
    revision_id = str(uuid.uuid4())
    session = sessions.create(match_id, revision_id, weapon_side_a, weapon_side_b)

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

    asyncio.ensure_future(forward_verdict.execute(revision_id))

    return OfferResponse(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type,
        match_id=match_id,
        revision_id=revision_id,
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
        "(ver shared.config.FAVERO_LUZ_TIMEOUT_S). Aplica a la sesión "
        "WebRTC más reciente del combate (POST /webrtc/offer); 404 si el "
        "combate no tiene ninguna."
    ),
    responses={404: {"description": "El combate no tiene una sesión WebRTC en curso."}},
)
@inject
async def webrtc_luz(
    match_id: str,
    body: LuzRequest,
    sessions: SessionRegistry = Depends(Provide[Container.sessions]),
) -> LuzAck:
    session = sessions.latest_for_match(match_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"el combate {match_id!r} no tiene una sesión WebRTC en curso (POST /webrtc/offer)",
        )
    session.set_luz(LuzSignal(has_luz_a=body.has_luz_A, has_luz_b=body.has_luz_B))
    return LuzAck(match_id=match_id, has_luz_A=body.has_luz_A, has_luz_B=body.has_luz_B)


def _respuesta_clip(
    match_id: str, revision_id: str, luz: LuzSignal, resultado: VerdictView | UnavailableResult
) -> ClipUploadResponse:
    if isinstance(resultado, VerdictView):
        return ClipUploadResponse(
            match_id=match_id,
            revision_id=revision_id,
            has_luz_A=luz.has_luz_a,
            has_luz_B=luz.has_luz_b,
            timed_out=False,
            disponible=True,
            motivo=None,
            fencer=resultado.fencer,
            action=resultado.action,
            confidence=resultado.confidence,
        )
    return ClipUploadResponse(
        match_id=match_id,
        revision_id=revision_id,
        has_luz_A=luz.has_luz_a,
        has_luz_B=luz.has_luz_b,
        timed_out=resultado.motivo == MotivoNoDisponible.TIMEOUT,
        disponible=False,
        motivo=resultado.motivo.value,
    )


@router.post(
    "/matches/{match_id}/clip",
    response_model=ClipUploadResponse,
    tags=["matches"],
    summary="Sube un clip con tocado simulado y abre la revisión VAR (CU-02, CU-03, CU-05)",
    description=(
        "Alternativa a POST /webrtc/offer para subir un clip ya grabado. "
        "Exige un combate creado con POST /matches/config (404 si no), "
        "`t_tocado_ms` y al menos una luz encendida (422 si falta alguna, "
        "CU-03 flujo 2a). Registra `clip` (archivo por SHA-256, fps, ancho, "
        "alto, duración), `tocado` (fuente='simulado') y `revision_var` "
        "(aceptada); no registra qué tirador pidió la revisión (D-04). "
        "Corre pose+tracking, extracción de 192 features y publicación en "
        "Redis hacia Cloud, espera (síncrona, con timeout) el veredicto, y "
        "registra la `clasificacion` (o el \"no disponible\" con su motivo) "
        "contra el modelo activo, con los keypoints crudos en .npz y la "
        "latencia desde la recepción del clip. Un combate admite N clips: "
        "cada uno abre su propia revisión y devuelve su `revision_id`, con "
        "el que se registra el veredicto y se abre el WebSocket. 400 si el archivo no abre "
        "como video o tiene menos de MIN_FRAMES frames; 413 si supera "
        "CLIP_MAX_MB (DEF-13); 503 si no hay versión de modelo activa. Con "
        "pose incompleta (DEF-08) responde de inmediato con "
        "disponible=false y motivo='pose_incompleta', sin esperar a Cloud."
    ),
    responses={
        404: {"description": "El combate no fue creado."},
        422: {"description": "Falta t_tocado_ms o no hay ninguna luz encendida."},
        503: {"description": "No hay versión de modelo activa."},
    },
)
@inject
async def upload_clip(
    match_id: str,
    file: UploadFile = File(..., description="Clip de video del combate (MP4/MOV)."),
    t_tocado_ms: int = Form(
        ..., ge=0, description="Instante del tocado simulado en ms desde el inicio del clip (RF-02). Obligatorio."
    ),
    has_luz_A: bool | None = Form(
        None, description="True si se encendió la luz Favero del tirador A."
    ),
    has_luz_B: bool | None = Form(
        None, description="True si se encendió la luz Favero del tirador B."
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
    uow: UnidadDeTrabajoPort = Depends(Provide[Container.unidad_de_trabajo]),
    file_storage: FileStoragePort = Depends(Provide[Container.file_storage]),
    abrir_revision: AbrirRevisionVar = Depends(Provide[Container.abrir_revision]),
    registrar_clasificacion: RegistrarClasificacion = Depends(Provide[Container.registrar_clasificacion]),
    verdict_timeout_s: float = Depends(Provide[Container.config.clip_upload_verdict_timeout_s]),
    clip_max_mb: float = Depends(Provide[Container.config.clip_max_mb]),
    min_frames: int = Depends(Provide[Container.config.min_frames]),
) -> ClipUploadResponse:
    recibido = time.monotonic()

    combate = await _combate_o_none(match_id, uow)
    if combate is None:
        raise _combate_no_creado(match_id)

    # has_luz_A/has_luz_B (bool) es la forma vigente (DEF-14); luz_frame_a/b
    # (índice de frame, reducido a booleano) queda como alias obsoleto para
    # clientes viejos, y solo se usa si los campos nuevos vienen ambos vacíos.
    if has_luz_A is None and has_luz_B is None:
        luz = LuzSignal(has_luz_a=luz_frame_a is not None, has_luz_b=luz_frame_b is not None)
    else:
        luz = LuzSignal(has_luz_a=bool(has_luz_A), has_luz_b=bool(has_luz_B))
    if not (luz.has_luz_a or luz.has_luz_b):
        raise HTTPException(
            status_code=422,
            detail="el tocado simulado requiere al menos una luz encendida (has_luz_A o has_luz_B)",
        )

    try:
        await registrar_clasificacion.verificar_modelo_activo()
    except SinModeloActivo as exc:
        raise HTTPException(
            status_code=503, detail="no hay una versión de modelo activa (scripts/registrar_modelo.py)"
        ) from exc

    try:
        clip = await process_uploaded_clip(
            file, pose_estimator, executor, file_storage,
            clip_max_mb=clip_max_mb, min_frames=min_frames,
        )
    except ClipTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except InvalidClipError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    revision = await abrir_revision.execute(
        combate=combate,
        video=VideoGuardado(
            uri=clip.uri,
            sha256=clip.sha256,
            fps=clip.fps,
            ancho_px=clip.ancho_px,
            alto_px=clip.alto_px,
            duracion_ms=clip.duracion_ms,
        ),
        luz=luz,
        t_tocado_ms=t_tocado_ms,
    )
    revision_id = str(revision.revision.id)
    session = sessions.create(
        match_id, revision_id, lado_de_brazo(combate.brazo_a), lado_de_brazo(combate.brazo_b)
    )
    session.set_luz(luz)
    session.t_tocado_ms = t_tocado_ms

    resultado: VerdictView | UnavailableResult | None = await process_match.execute(
        match_id, revision_id, clip.tracked, session.weapon_side_a, session.weapon_side_b, luz
    )
    # Si la extracción falló (pose incompleta) no se publicó nada en Redis:
    # no tiene sentido esperar a Cloud (DEF-08).
    if resultado is None:
        try:
            await asyncio.wait_for(forward_verdict.execute(revision_id), timeout=verdict_timeout_s)
        except asyncio.TimeoutError:
            # DEF-16: sin esto, esta sesión nunca queda "cerrada" (closed_at
            # sigue None) y sweep_expired no la libera jamás.
            resultado = UnavailableResult(
                match_id=match_id, revision_id=revision_id, motivo=MotivoNoDisponible.TIMEOUT
            )
            await session.set_unavailable(resultado)
        else:
            resultado = session.verdict or session.unavailable
            if resultado is None:
                resultado = UnavailableResult(
                    match_id=match_id, revision_id=revision_id, motivo=MotivoNoDisponible.TIMEOUT
                )

    await registrar_clasificacion.execute(
        tocado_id=revision.tocado.id,
        revision_id=revision.revision.id,
        tracked=clip.tracked,
        resultado=resultado,
        latencia_ms=int((time.monotonic() - recibido) * 1000),
    )
    return _respuesta_clip(match_id, revision_id, luz, resultado)


@router.post(
    "/revisiones/{revision_id}/veredicto",
    response_model=VeredictoResponse,
    tags=["revisiones"],
    summary="Registra el veredicto final del árbitro y cierra la revisión (CU-10, CU-11)",
    description=(
        "Sobre la revisión indicada (un combate admite N; cada clip devuelve "
        "su `revision_id`), en una sola transacción: inserta el `veredicto`, cierra la `revision_var` "
        "(`cerrada_en`) e inserta el `registro_auditoria` con el snapshot "
        "(revisión, tocado, clasificación, veredicto, modelo y reglamento). "
        "Sin veredicto la revisión no se cierra (RF-21); el sistema solo "
        "sugiere, nunca asigna el punto (RNF-01). `decision` describe la "
        "relación con la decisión original del árbitro en pista y "
        "`clase_final` es siempre la decisión final declarada: obligatoria "
        "con 'mantener' y 'cambiar' (422 si falta, aunque la clasificación "
        "no estuviera disponible) y prohibida con 'anular' (422 si viene). "
        "409 si la revisión ya tiene veredicto o aún no tiene clasificación."
    ),
    responses={
        404: {"description": "La revisión o el árbitro no existen."},
        409: {"description": "La revisión ya tiene veredicto, o no tiene clasificación registrada."},
        422: {"description": "'mantener' o 'cambiar' sin clase_final, 'anular' con clase_final, o clase fuera de dominio."},
    },
)
@inject
async def registrar_veredicto(
    revision_id: str,
    body: VeredictoRequest,
    caso: RegistrarVeredicto = Depends(Provide[Container.registrar_veredicto]),
) -> VeredictoResponse:
    try:
        revision_uuid = uuid.UUID(revision_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail=f"no existe: revisión {revision_id!r}"
        ) from exc
    try:
        registrado = await caso.execute(
            revision_id=revision_uuid,
            decision=body.decision,
            clase_final=body.clase_final,
            arbitro_id=body.arbitro_id,
        )
    except RecursoNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=f"no existe: {exc}") from exc
    except VeredictoYaRegistrado as exc:
        raise HTTPException(status_code=409, detail="la revisión ya tiene un veredicto registrado") from exc
    except ClasificacionPendiente as exc:
        raise HTTPException(
            status_code=409, detail="la revisión aún no tiene una clasificación registrada"
        ) from exc
    except VeredictoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    v = registrado.veredicto
    return VeredictoResponse(
        match_id=str(registrado.combate_id),
        revision_id=registrado.revision.id,
        veredicto_id=v.id,
        decision=v.decision,
        clase_final=v.clase_final,
        arbitro_id=v.arbitro_id,
        registrado_en=v.registrado_en,
        cerrada_en=registrado.revision.cerrada_en,
        auditoria_seq=registrado.auditoria.seq,
        auditoria_hash=registrado.auditoria.hash,
    )


@router.websocket("/ws/veredicto/{revision_id}")
@inject
async def ws_veredicto(
    websocket: WebSocket,
    revision_id: str,
    sessions: SessionRegistry = Depends(Provide[Container.sessions]),
):
    """No aparece en Swagger (las rutas WebSocket no son parte de OpenAPI),
    documentado en CONTRATO_API.md y en VerdictMessage/NoDisponibleMessage
    (schemas.py). Envía un único mensaje JSON —veredicto o no_disponible—
    en cuanto el resultado está disponible (DEF-08). Se identifica por
    `revision_id`; si la revisión no tiene una sesión activa en Fog,
    rechaza el handshake con 404."""
    session = sessions.get(revision_id)
    if session is None:
        if "websocket.http.response" in websocket.scope.get("extensions", {}):
            await websocket.send_denial_response(
                JSONResponse(
                    status_code=404,
                    content={"detail": f"la revisión {revision_id!r} no tiene una sesión activa"},
                )
            )
        else:
            # El servidor no soporta respuestas HTTP de rechazo: se cierra con
            # 1008 (violación de política) antes de aceptar.
            await websocket.close(code=1008)
        return

    await websocket.accept()
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
