"""Rutas de autenticación: POST /auth/login y GET /auth/me (DEPLOY05).

Sin lista de revocación: el logout es del cliente (borrar el token) y un token
robado sigue siendo válido hasta su expiración (8 h). Limitación documentada
en CONTRATO_API.md.
"""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from fog.application.autenticar import IniciarSesion
from fog.composition import Container
from fog.domain.errors import CredencialesInvalidas, DemasiadosIntentos
from fog.infrastructure.api.seguridad import exigir_autenticacion, ip_cliente

router_login = APIRouter(prefix="/auth", tags=["autenticación"])
router_sesion = APIRouter(prefix="/auth", tags=["autenticación"])


class LoginRequest(BaseModel):
    # Los máximos evitan que una contraseña enorme encarezca el hash.
    usuario: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    expires_in: int = Field(..., description="Vigencia del token en segundos.")


class SesionResponse(BaseModel):
    usuario: str


@router_login.post(
    "/login",
    response_model=LoginResponse,
    summary="Iniciar sesión (usuario maestro)",
    description=(
        "Devuelve un JWT HS256 de 8 h. 401 con mensaje único si usuario o "
        "contraseña son incorrectos. 5 fallos en 15 min por IP bloquean la IP "
        "15 min (429 con `Retry-After`)."
    ),
    responses={
        401: {"description": "Credenciales inválidas."},
        429: {"description": "IP bloqueada por demasiados intentos."},
        503: {"description": "El control de intentos no está disponible."},
    },
)
@inject
async def login(
    cuerpo: LoginRequest,
    request: Request,
    caso: IniciarSesion = Depends(Provide[Container.iniciar_sesion]),
) -> LoginResponse:
    try:
        token = await caso.execute(cuerpo.usuario, cuerpo.password, ip_cliente(request))
    except DemasiadosIntentos as exc:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Intente más tarde.",
            headers={"Retry-After": str(exc.reintentar_en_s)},
        ) from None
    except CredencialesInvalidas:
        raise HTTPException(status_code=401, detail="Credenciales inválidas") from None
    except RedisError:
        raise HTTPException(
            status_code=503, detail="Servicio de autenticación no disponible"
        ) from None
    return LoginResponse(access_token=token.access_token, expires_in=token.expires_in)


@router_sesion.get(
    "/me",
    response_model=SesionResponse,
    summary="Usuario de la sesión",
    description="Permite al frontend validar que el token sigue vigente.",
    responses={401: {"description": "Token ausente, vencido o alterado."}},
)
async def me(usuario: str = Depends(exigir_autenticacion)) -> SesionResponse:
    return SesionResponse(usuario=usuario)
