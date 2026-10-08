"""Fábrica de la app FastAPI de Fog con el endurecimiento de DEPLOY05.

Reúne routers, CORS cerrado, token de proxy, cabeceras de seguridad y el
apagado de la documentación en el despliegue remoto. `main.py` y las pruebas
usan la misma fábrica, así lo que se prueba es lo que se despliega.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fog.infrastructure.api import auth_routes, routes, seguridad
from shared import config

# Módulos con `Provide[...]` que el Container debe cablear.
MODULOS_WIRING = [routes, seguridad, auth_routes]


def crear_app(
    *,
    entorno: str | None = None,
    proxy_token: str | None = None,
    cors_origins: list[str] | None = None,
    **kwargs,
) -> FastAPI:
    """Arma la app de Fog.

    Args:
        entorno: `remoto` apaga /docs, /redoc, /openapi.json y /ws/veredicto.
            Por defecto `config.ENTORNO`.
        proxy_token: valor esperado en `X-Proxy-Token`; None no lo exige.
            Por defecto `config.PROXY_SHARED_TOKEN`.
        cors_origins: orígenes CORS permitidos, sin comodines. Por defecto
            `config.cors_origins()`.
        **kwargs: argumentos de `FastAPI` (título, lifespan, ...).

    Returns:
        La app configurada.

    Raises:
        RuntimeError: si `cors_origins` contiene un comodín.
    """
    entorno = config.ENTORNO if entorno is None else entorno
    proxy_token = config.PROXY_SHARED_TOKEN if proxy_token is None else proxy_token
    cors_origins = config.cors_origins() if cors_origins is None else cors_origins
    if "*" in cors_origins:
        raise RuntimeError("CORS_ORIGINS no admite comodines: listar cada origen.")

    remoto = entorno == "remoto"
    if remoto:
        kwargs.update(docs_url=None, redoc_url=None, openapi_url=None)
    app = FastAPI(**kwargs)
    app.state.proxy_token = proxy_token

    app.include_router(routes.router_publico)
    app.include_router(auth_routes.router_login)
    app.include_router(auth_routes.router_sesion)
    app.include_router(routes.router)
    if not remoto:
        # WebRTC no se usa en la Validación 1; en remoto no se expone.
        app.include_router(routes.router_ws)

    # El último agregado es el más externo: cabeceras > token de proxy > CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(seguridad.TokenDeProxy, token=proxy_token)
    app.add_middleware(seguridad.EncabezadosSeguridad)
    return app
