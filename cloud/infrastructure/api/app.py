"""API HTTP de entrada de Cloud (DEPLOY11): un adaptador más sobre `ClasificarSecuencia`.

- `GET /health`: sin autenticación ni datos sensibles.
- `POST /v1/clasificar`: recibe las features de una revisión y devuelve el veredicto. Exige
  `Authorization: Bearer <token>` de un nodo registrado (`RegistroNodos`).

Cloud no persiste lo que recibe. Los logs llevan el nombre del nodo, el código y el tiempo; nunca
el contenido de la petición ni el token.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from cloud.application.clasificar_secuencia import ClasificarSecuencia
from cloud.domain.models import LuzSignal, Verdict
from cloud.domain.secuencia_features import ContratoInvalidoError, construir_secuencia
from cloud.infrastructure.api.limite_cuerpo import LimiteCuerpo
from cloud.infrastructure.api.nodos import LimitadorPeticiones, RegistroNodos
from cloud.infrastructure.api.schemas import RespuestaClasificar, SolicitudClasificar
from shared import config

log = logging.getLogger("cloud.api")

_ENCABEZADOS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _error(estado: int, detalle: str, **extra) -> JSONResponse:
    return JSONResponse({"detail": detalle}, status_code=estado, headers={**_ENCABEZADOS, **extra})


def _token_bearer(request: Request) -> str | None:
    valor = request.headers.get("authorization", "")
    esquema, _, token = valor.partition(" ")
    token = token.strip()
    return token if esquema.lower() == "bearer" and token else None


def _respuesta(veredicto: Verdict) -> RespuestaClasificar:
    return RespuestaClasificar(
        match_id=veredicto.match_id,
        revision_id=veredicto.revision_id,
        disponible=veredicto.disponible,
        action_class=veredicto.action_class.value if veredicto.action_class else None,
        confidence=veredicto.confidence,
        fencer=veredicto.fencer,
        probs=veredicto.probs,
        latencia_inferencia_ms=veredicto.latencia_inferencia_ms,
        modelo=veredicto.modelo,
        atencion=[round(w, 4) for w in veredicto.atencion] if veredicto.atencion is not None else None,
        motivo_no_disp=veredicto.motivo_no_disp,
    )


def crear_app(
    clasificar: ClasificarSecuencia,
    nodos: RegistroNodos,
    *,
    limitador: LimitadorPeticiones | None = None,
    max_body_bytes: int | None = None,
    timeout_s: float | None = None,
    entorno: str | None = None,
) -> FastAPI:
    """Arma la app HTTP de Cloud.

    Args:
        clasificar: caso de uso de clasificación (el mismo que usa el consumidor de Redis).
        nodos: registro de hashes de tokens por nodo.
        limitador: límite de peticiones por nodo; por defecto el de `shared.config`.
        max_body_bytes: tamaño máximo del cuerpo; por defecto `CLOUD_HTTP_MAX_BODY_BYTES`.
        timeout_s: tiempo máximo por petición; por defecto `CLOUD_HTTP_PETICION_TIMEOUT_S`.
        entorno: `remoto` apaga /docs, /redoc y /openapi.json; por defecto `config.ENTORNO`.

    Returns:
        La aplicación FastAPI.
    """
    entorno = config.ENTORNO if entorno is None else entorno
    limitador = limitador or LimitadorPeticiones(
        config.CLOUD_HTTP_LIMITE_PETICIONES, config.CLOUD_HTTP_LIMITE_VENTANA_S
    )
    max_body_bytes = config.CLOUD_HTTP_MAX_BODY_BYTES if max_body_bytes is None else max_body_bytes
    timeout_s = config.CLOUD_HTTP_PETICION_TIMEOUT_S if timeout_s is None else timeout_s
    # Una sola inferencia a la vez: el modelo no se comparte entre hilos y las demás esperan en cola.
    ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clasificador")

    kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if entorno == "remoto" else {}
    app = FastAPI(title="SABRE.AI Cloud", **kwargs)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"}, headers=_ENCABEZADOS)

    @app.post("/v1/clasificar", response_model=RespuestaClasificar, response_model_exclude_none=True)
    async def clasificar_features(request: Request):
        inicio = time.perf_counter()
        token = _token_bearer(request)
        nodo = nodos.autenticar(token) if token else None
        if nodo is None:
            log.warning("petición rechazada: token ausente o no autorizado (401)")
            return _error(401, "No autorizado.", **{"WWW-Authenticate": "Bearer"})
        if not limitador.permitir(nodo):
            log.warning("[%s] límite de peticiones superado (429)", nodo)
            return _error(429, "Demasiadas peticiones.", **{"Retry-After": "60"})

        estado, cuerpo = 200, None
        try:
            try:
                solicitud = SolicitudClasificar.model_validate_json(await request.body())
            except ValidationError as e:
                # Solo ubicación y mensaje: el error de pydantic incluiría el valor recibido.
                estado = 422
                return JSONResponse(
                    {"detail": [{"campo": ".".join(str(p) for p in err["loc"]), "motivo": err["msg"]}
                                for err in e.errors()]},
                    status_code=422, headers=_ENCABEZADOS,
                )
            try:
                buffer = base64.b64decode(solicitud.features, validate=True)
                secuencia = construir_secuencia(
                    match_id=solicitud.match_id,
                    revision_id=solicitud.revision_id,
                    shape=solicitud.shape,
                    dtype=solicitud.dtype,
                    buffer=buffer,
                    luz=LuzSignal(has_luz_a=solicitud.has_luz_A, has_luz_b=solicitud.has_luz_B),
                    weapon_side_a=solicitud.weapon_side_A,
                    weapon_side_b=solicitud.weapon_side_B,
                )
            except (binascii.Error, ContratoInvalidoError) as e:
                estado = 422
                detalle = "features no es base64 válido" if isinstance(e, binascii.Error) else str(e)
                return _error(422, detalle)

            try:
                bucle = asyncio.get_running_loop()
                veredicto = await asyncio.wait_for(
                    bucle.run_in_executor(ejecutor, clasificar.execute, secuencia), timeout_s
                )
            except asyncio.TimeoutError:
                estado = 504
                return _error(504, "La clasificación superó el tiempo máximo.")
            except Exception:
                estado = 500
                log.exception("[%s] fallo clasificando", nodo)
                return _error(500, "Fallo interno al clasificar.")
            cuerpo = _respuesta(veredicto)
            return JSONResponse(cuerpo.model_dump(exclude_none=True), headers=_ENCABEZADOS)
        finally:
            log.info(
                "[%s] POST /v1/clasificar -> %d en %d ms%s", nodo, estado,
                (time.perf_counter() - inicio) * 1000,
                f" (T={cuerpo.atencion and len(cuerpo.atencion)})" if cuerpo else "",
            )

    app.add_middleware(LimiteCuerpo, maximo_bytes=max_body_bytes)
    return app
