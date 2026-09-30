"""Router HTTP/WebSocket de Fog. Documentado para Swagger (summary,
description, response_model, tags) por pedido explícito de Nicolas. La
resolución de dependencias usa dependency_injector (Provide[...] + @inject,
ver fog/composition.py) — wiring registrado en fog/main.py.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any
from datetime import datetime, timezone
from concurrent.futures import Executor

from aiortc import RTCPeerConnection, RTCSessionDescription
from dependency_injector.wiring import Provide, inject
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse

from fog.application.abrir_revision import AbrirRevisionVar, VideoGuardado
from fog.application.configurar_combate import ConfigurarCombate, DatosTirador
from fog.application.consultar_combate import ObtenerCombate
from fog.application.consultar_revisiones import (
    ConsultarSalud,
    ListarRevisiones,
    ObtenerModeloActivo,
    ObtenerRevision,
    VerificarAuditoria,
)
from fog.application.forward_verdict import ForwardVerdictToClient
from fog.application.listar_catalogos import ListarEventos, ListarUsuarios
from fog.application.process_match import ProcessIncomingMatch
from fog.application.registrar_clasificacion import RegistrarClasificacion
from fog.application.registrar_veredicto import RegistrarVeredicto
from fog.application.resumir_validacion import ResumirValidacion
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
    InstantesLuz,
    LuzSignal,
    MotivoNoDisponible,
    UnavailableResult,
    VerdictView,
    WeaponSide,
    lado_de_brazo,
)
from fog.infrastructure.api.schemas import (
    AuditoriaVerificarResponse,
    ClipUploadResponse,
    CombateResponse,
    EventoResponse,
    HealthResponse,
    LuzAck,
    LuzRequest,
    MatchConfigRequest,
    MatchConfigResponse,
    ModeloActivoResponse,
    OfferRequest,
    OfferResponse,
    RegistroAlteradoResponse,
    RevisionDetalleResponse,
    RevisionResumenResponse,
    RolLiteral,
    SugerenciaResponse,
    UsuarioResponse,
    VeredictoRequest,
    VeredictoResponse,
)
from fog.infrastructure.clips.clip_file_reader import (
    ClipTooLargeError,
    InvalidClipError,
    TocadoFueraDelClipError,
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


@router.get(
    "/eventos",
    response_model=list[EventoResponse],
    tags=["configuración"],
    summary="Lista los eventos (solo lectura)",
    description=(
        "Eventos de `sabre.evento`, del más reciente al más antiguo, para que "
        "la pantalla de configuración elija el `evento_id` de POST "
        "/matches/config. No crea ni modifica nada: los eventos se siembran "
        "con scripts/crear_sesion_validacion.py."
    ),
)
@inject
async def listar_eventos(
    caso: ListarEventos = Depends(Provide[Container.listar_eventos]),
) -> list[EventoResponse]:
    eventos = await caso.execute()
    return [
        EventoResponse(id=e.id, nombre=e.nombre, fecha=e.fecha, lugar=e.lugar, tipo=e.tipo)
        for e in eventos
    ]


@router.get(
    "/usuarios",
    response_model=list[UsuarioResponse],
    tags=["configuración"],
    summary="Lista los usuarios, opcionalmente por rol (solo lectura)",
    description=(
        "Usuarios de `sabre.usuario` ordenados por nombre. Con "
        "`?rol=arbitro` devuelve solo los árbitros, para elegir el "
        "`arbitro_id` de POST /matches/config; `rol` admite `arbitro`, "
        "`operador` o `administrador` (422 con otro valor). Incluye `activo`. "
        "No crea ni modifica nada: los usuarios se siembran con "
        "scripts/crear_sesion_validacion.py (no hay login, RF-26 es COULD)."
    ),
    responses={422: {"description": "`rol` no es un rol del esquema."}},
)
@inject
async def listar_usuarios(
    rol: RolLiteral | None = Query(None, description="Filtra por rol."),
    caso: ListarUsuarios = Depends(Provide[Container.listar_usuarios]),
) -> list[UsuarioResponse]:
    usuarios = await caso.execute(rol)
    return [
        UsuarioResponse(id=u.id, nombre=u.nombre, rol=u.rol, activo=u.activo) for u in usuarios
    ]


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
            ),
            tirador_b=DatosTirador(
                alias=body.alias_B,
                weapon_side=WeaponSide(body.weapon_side_B),
            ),
        )
    except RecursoNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=f"no existe: {exc}") from exc
    return MatchConfigResponse(
        match_id=str(combate.id),
        weapon_side_A=body.weapon_side_A,
        weapon_side_B=body.weapon_side_B,
    )


@router.get(
    "/matches/{match_id}",
    response_model=CombateResponse,
    tags=["matches"],
    summary="Combate configurado (solo lectura)",
    description=(
        "Pista, árbitro, alias y brazo armado de A y B del combate creado con "
        "POST /matches/config. El frontend lo usa para validar el combate "
        "activo que recuerda entre recargas. No crea ni modifica nada. 404 si "
        "el combate no existe o `match_id` no es uuid."
    ),
    responses={404: {"description": "El combate no existe."}},
)
@inject
async def obtener_combate(
    match_id: str,
    caso: ObtenerCombate = Depends(Provide[Container.obtener_combate]),
) -> CombateResponse:
    try:
        combate_uuid = uuid.UUID(match_id)
    except ValueError as exc:
        raise _combate_no_creado(match_id) from exc
    try:
        c = await caso.execute(combate_uuid)
    except RecursoNoEncontrado as exc:
        raise _combate_no_creado(match_id) from exc
    return CombateResponse(
        match_id=str(c.id),
        pista=c.pista,
        arbitro_id=c.arbitro_id,
        arbitro=c.arbitro,
        alias_A=c.alias_a,
        weapon_side_A=lado_de_brazo(c.brazo_a).value,
        alias_B=c.alias_b,
        weapon_side_B=lado_de_brazo(c.brazo_b).value,
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
        "`t_luz_a_ms` y/o `t_luz_b_ms` (al menos uno, CU-03 flujo 2a; 422 si "
        "no hay ninguno). Cada instante debe estar entre 0 y la duración del "
        "clip, ambos incluidos (422 si no). La luz encendida se deduce de que "
        "exista su instante y `t_tocado_ms` es el menor de los dos, calculado "
        "en el servidor. `has_luz_A/B` con `t_tocado_ms` son alias obsoletos. "
        "Registra `clip` (archivo por SHA-256, fps, ancho, "
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
        422: {
            "description": (
                "Ninguna luz con instante, o un instante fuera de [0, duración del clip]."
            )
        },
        503: {"description": "No hay versión de modelo activa."},
    },
)
@inject
async def upload_clip(
    match_id: str,
    file: UploadFile = File(..., description="Clip de video del combate (MP4/MOV)."),
    t_luz_a_ms: int | None = Form(
        None, ge=0, description=(
            "Instante de la luz Favero de A en ms desde el inicio del clip (RF-02); entre 0 y la "
            "duración del clip. Omitido = luz de A apagada."
        )
    ),
    t_luz_b_ms: int | None = Form(
        None, ge=0, description=(
            "Instante de la luz Favero de B en ms desde el inicio del clip (RF-02); entre 0 y la "
            "duración del clip. Omitido = luz de B apagada."
        )
    ),
    t_tocado_ms: int | None = Form(
        None, ge=0, description=(
            "[OBSOLETO] Instante único del tocado. Solo se usa si se omiten t_luz_a_ms y "
            "t_luz_b_ms: queda como instante de cada luz encendida por has_luz_A/has_luz_B. "
            "Con t_luz_a_ms/t_luz_b_ms se ignora: t_tocado_ms lo calcula el servidor."
        )
    ),
    has_luz_A: bool | None = Form(
        None, description="[OBSOLETO] True si se encendió la luz de A. Preferir t_luz_a_ms."
    ),
    has_luz_B: bool | None = Form(
        None, description="[OBSOLETO] True si se encendió la luz de B. Preferir t_luz_b_ms."
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

    # t_luz_a_ms/t_luz_b_ms es la forma vigente (V02). has_luz_A/B + t_tocado_ms
    # y luz_frame_a/b (índice de frame, reducido a booleano) quedan como alias
    # obsoletos para clientes viejos y solo se usan si ambos instantes vienen vacíos.
    if t_luz_a_ms is None and t_luz_b_ms is None:
        if has_luz_A is None and has_luz_B is None:
            luz_a, luz_b = luz_frame_a is not None, luz_frame_b is not None
        else:
            luz_a, luz_b = bool(has_luz_A), bool(has_luz_B)
        if not (luz_a or luz_b):
            raise HTTPException(
                status_code=422,
                detail="el tocado simulado requiere al menos una luz (t_luz_a_ms o t_luz_b_ms)",
            )
        if t_tocado_ms is None:
            raise HTTPException(
                status_code=422,
                detail="falta el instante de la luz encendida (t_luz_a_ms o t_luz_b_ms)",
            )
        t_luz_a_ms = t_tocado_ms if luz_a else None
        t_luz_b_ms = t_tocado_ms if luz_b else None
    instantes = InstantesLuz(t_luz_a_ms=t_luz_a_ms, t_luz_b_ms=t_luz_b_ms)
    luz = instantes.luz
    t_tocado_ms = instantes.t_tocado_ms

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
            instantes_ms={
                nombre: valor
                for nombre, valor in (("t_luz_a_ms", t_luz_a_ms), ("t_luz_b_ms", t_luz_b_ms))
                if valor is not None
            },
        )
    except ClipTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except InvalidClipError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TocadoFueraDelClipError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
        instantes=instantes,
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


def _con_zona_horaria(instante: datetime | None) -> datetime | None:
    """Un instante sin zona horaria se interpreta como UTC."""
    if instante is not None and instante.tzinfo is None:
        return instante.replace(tzinfo=timezone.utc)
    return instante


@router.get(
    "/revisiones",
    response_model=list[RevisionResumenResponse],
    tags=["revisiones"],
    summary="Lista resumida de revisiones (solo lectura)",
    description=(
        "Revisiones de la más reciente a la más antigua. Filtros opcionales: "
        "`evento_id` (evento del combate) y `desde`/`hasta` sobre "
        "`revision_var.abierta_en`, ISO 8601 e inclusivos; un instante sin "
        "zona horaria se interpreta como UTC. Sin filtros devuelve todas. "
        "422 si `evento_id` no es uuid o una fecha no es ISO 8601."
    ),
    responses={422: {"description": "`evento_id`, `desde` o `hasta` inválidos."}},
)
@inject
async def listar_revisiones(
    evento_id: uuid.UUID | None = Query(None, description="Solo revisiones de combates de este evento."),
    desde: datetime | None = Query(None, description="Abiertas en o después de este instante."),
    hasta: datetime | None = Query(None, description="Abiertas en o antes de este instante."),
    caso: ListarRevisiones = Depends(Provide[Container.listar_revisiones]),
) -> list[RevisionResumenResponse]:
    resumenes = await caso.execute(
        evento_id=evento_id, desde=_con_zona_horaria(desde), hasta=_con_zona_horaria(hasta)
    )
    return [RevisionResumenResponse(**vars(r)) for r in resumenes]


@router.get(
    "/revisiones/{revision_id}",
    response_model=RevisionDetalleResponse,
    tags=["revisiones"],
    summary="Detalle de una revisión (solo lectura)",
    description=(
        "Sugerencia del sistema, probabilidades, decisión del árbitro y hash "
        "de auditoría. Los campos que aún no existen (clasificación pendiente, "
        "sin veredicto, revisión no cerrada) son null. 404 si la revisión no "
        "existe o `revision_id` no es uuid."
    ),
    responses={404: {"description": "La revisión no existe."}},
)
@inject
async def obtener_revision(
    revision_id: str,
    caso: ObtenerRevision = Depends(Provide[Container.obtener_revision]),
) -> RevisionDetalleResponse:
    try:
        revision_uuid = uuid.UUID(revision_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail=f"no existe: revisión {revision_id!r}"
        ) from exc
    try:
        d = await caso.execute(revision_uuid)
    except RecursoNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=f"no existe: {exc}") from exc
    sugerencia = (
        SugerenciaResponse(
            disponible=d.disponible,
            motivo_no_disp=d.motivo_no_disp,
            clase=d.clase,
            tirador=d.tirador,
            confianza=d.confianza,
        )
        if d.disponible is not None
        else None
    )
    return RevisionDetalleResponse(
        id=d.id,
        combate_id=d.combate_id,
        abierta_en=d.abierta_en,
        cerrada_en=d.cerrada_en,
        sugerencia=sugerencia,
        probabilidades=d.probabilidades,
        decision=d.decision,
        clase_final=d.clase_final,
        registrado_en=d.registrado_en,
        auditoria_seq=d.auditoria_seq,
        auditoria_hash=d.auditoria_hash,
    )


@router.get(
    "/auditoria/verificar",
    response_model=AuditoriaVerificarResponse,
    tags=["auditoría"],
    summary="Verifica la cadena de hashes de la auditoría (solo lectura)",
    description=(
        "Resultado de `sabre.fn_verificar_auditoria()` sin filtrar: "
        "`alteradas` lista los registros cuyo hash guardado no coincide con "
        "el recalculado, e `integra` es true si no hay ninguno. Responde 200 "
        "en ambos casos."
    ),
)
@inject
async def verificar_auditoria(
    caso: VerificarAuditoria = Depends(Provide[Container.verificar_auditoria]),
) -> AuditoriaVerificarResponse:
    alterados = await caso.execute()
    return AuditoriaVerificarResponse(
        integra=not alterados,
        alteradas=[RegistroAlteradoResponse(**vars(a)) for a in alterados],
    )


@router.get(
    "/validaciones/{evento_id}/resumen",
    response_model=dict[str, Any],
    tags=["validación"],
    summary="Resumen de la sesión de validación de un evento (solo lectura)",
    description=(
        "Mismo contenido que `resumen.json` de scripts/exportar_evidencia.py "
        "(L02): métricas separadas en V1 y V2, conciliación con el JSONL de "
        "L01, integridad de la auditoría y evidencia del modelo. Se calcula "
        "desde PostgreSQL. Sin autenticación (RF-26 está pendiente). 404 si "
        "el evento no existe."
    ),
    responses={404: {"description": "El evento no existe."}},
)
@inject
async def resumen_validacion(
    evento_id: uuid.UUID,
    caso: ResumirValidacion = Depends(Provide[Container.resumir_validacion]),
) -> dict[str, Any]:
    try:
        return (await caso.execute(evento_id)).resumen
    except RecursoNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/modelo/activo",
    response_model=ModeloActivoResponse,
    tags=["modelo"],
    summary="Versión de modelo activa y sus métricas registradas (solo lectura)",
    description=(
        "Nombre, número de clases y métricas registradas en `modelo_version` "
        "(`f1_macro_test`, `kappa_piloto`; null si no se registraron). 404 si "
        "no hay versión activa (scripts/registrar_modelo.py)."
    ),
    responses={404: {"description": "No hay versión de modelo activa."}},
)
@inject
async def modelo_activo(
    caso: ObtenerModeloActivo = Depends(Provide[Container.obtener_modelo_activo]),
) -> ModeloActivoResponse:
    try:
        modelo = await caso.execute()
    except SinModeloActivo as exc:
        raise HTTPException(status_code=404, detail="no hay una versión de modelo activa") from exc
    return ModeloActivoResponse(
        nombre=modelo.nombre,
        num_clases=modelo.num_clases,
        f1_macro_test=modelo.f1_macro_test,
        kappa_piloto=modelo.kappa_piloto,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["salud"],
    summary="Estado de Fog, Redis y PostgreSQL",
    description=(
        "`ok` o `error` por componente. Fog es `ok` si responde. Redis "
        "(PING) y PostgreSQL (SELECT 1) tienen 2 s de tiempo límite. 200 si "
        "todo está `ok`; 503 con el mismo cuerpo si alguno falla."
    ),
    responses={503: {"model": HealthResponse, "description": "Redis o PostgreSQL no responden."}},
)
@inject
async def health(
    caso: ConsultarSalud = Depends(Provide[Container.consultar_salud]),
) -> JSONResponse:
    estado = await caso.execute()
    cuerpo = {
        nombre: "ok" if responde else "error"
        for nombre, responde in (
            ("fog", estado.fog),
            ("redis", estado.redis),
            ("postgres", estado.postgres),
        )
    }
    return JSONResponse(cuerpo, status_code=200 if estado.ok else 503)


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
