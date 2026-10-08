"""Autenticación del usuario maestro y endurecimiento de Fog (DEPLOY05).

Cubre login, bloqueo por intentos, protección de todas las rutas, token de
proxy, CORS, cabeceras de seguridad, documentación en modo remoto y registro
de eventos. App completa contra PostgreSQL real (conftest.py: `crear_app`);
solo se doblan pose, extractor, Redis (fakeredis) y Cloud.
"""

import logging
import time

import jwt
import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.testclient import TestClient

from tests.fog.conftest import (
    AUTH_PASSWORD,
    AUTH_SECRETO,
    AUTH_USUARIO,
    encabezado_auth,
)

LOGIN = {"usuario": AUTH_USUARIO, "password": AUTH_PASSWORD}
MALO = {"usuario": AUTH_USUARIO, "password": "otra-clave-incorrecta"}


def _rutas(router):
    """Rutas de la app, aplanando los routers incluidos.

    FastAPI reciente deja los routers incluidos como `_IncludedRouter`
    (con `original_router`); se desciende por ese atributo.
    """
    for ruta in router.routes:
        interno = getattr(ruta, "original_router", None)
        if interno is not None:
            yield from _rutas(interno)
        else:
            yield ruta


def _sin_token(app) -> TestClient:
    """Cliente sin credenciales sobre la misma app."""
    return TestClient(app.fastapi, raise_server_exceptions=False)


# --- Login -----------------------------------------------------------------


def test_login_correcto_devuelve_token(crear_app):
    app = crear_app(autenticado=False)

    resp = app.client.post("/auth/login", json=LOGIN)

    assert resp.status_code == 200
    cuerpo = resp.json()
    assert set(cuerpo) == {"access_token", "expires_in"}
    assert cuerpo["expires_in"] == 8 * 3600
    claims = jwt.decode(cuerpo["access_token"], AUTH_SECRETO, algorithms=["HS256"])
    assert set(claims) == {"sub", "iat", "exp", "jti"}
    assert claims["sub"] == AUTH_USUARIO
    assert claims["exp"] - claims["iat"] == 8 * 3600


def test_login_incorrecto_da_401_con_mensaje_generico(crear_app):
    app = crear_app(autenticado=False)

    mala_clave = app.client.post("/auth/login", json=MALO)
    mal_usuario = app.client.post("/auth/login", json={**LOGIN, "usuario": "otro"})

    assert mala_clave.status_code == mal_usuario.status_code == 401
    assert mala_clave.json() == mal_usuario.json() == {"detail": "Credenciales inválidas"}


def test_sexto_intento_da_429_aunque_la_clave_sea_correcta(crear_app):
    app = crear_app(autenticado=False)

    primeros = [app.client.post("/auth/login", json=MALO).status_code for _ in range(5)]
    sexto = app.client.post("/auth/login", json=LOGIN)

    assert primeros == [401] * 5
    assert sexto.status_code == 429
    assert 0 < int(sexto.headers["Retry-After"]) <= 900


def test_un_login_correcto_reinicia_el_contador(crear_app):
    app = crear_app(autenticado=False)
    for _ in range(4):
        app.client.post("/auth/login", json=MALO)

    assert app.client.post("/auth/login", json=LOGIN).status_code == 200
    # Si no se hubiera reiniciado, este 5.º fallo seguido ya bloquearía.
    for _ in range(4):
        assert app.client.post("/auth/login", json=MALO).status_code == 401


def test_login_rechaza_contrasena_gigante(crear_app):
    app = crear_app(autenticado=False)

    resp = app.client.post("/auth/login", json={**LOGIN, "password": "x" * 5000})

    assert resp.status_code == 422


# --- Protección de rutas ---------------------------------------------------


def test_sin_token_da_401_en_ruta_protegida(crear_app):
    app = crear_app(autenticado=False)

    resp = app.client.get("/eventos")

    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_token_vencido_da_401(crear_app):
    app = crear_app(autenticado=False)
    ahora = int(time.time())
    vencido = jwt.encode(
        {"sub": AUTH_USUARIO, "iat": ahora - 100, "exp": ahora - 10, "jti": "x"},
        AUTH_SECRETO, algorithm="HS256",
    )

    resp = app.client.get("/eventos", headers={"Authorization": f"Bearer {vencido}"})

    assert resp.status_code == 401


def test_token_con_firma_alterada_da_401(crear_app):
    app = crear_app(autenticado=False)
    valido = encabezado_auth(app.container)["Authorization"].split()[1]
    cabecera, claims, firma = valido.split(".")
    alterado = f"{cabecera}.{claims}.{firma[:-3]}{'AAA' if firma[-3:] != 'AAA' else 'BBB'}"
    falsificado = jwt.encode(
        {"sub": AUTH_USUARIO, "iat": 1, "exp": 9999999999, "jti": "x"},
        "otro-secreto-de-48-bytes-" + "z" * 30, algorithm="HS256",
    )

    for token in (alterado, falsificado, "basura"):
        resp = app.client.get("/eventos", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, token


def test_token_sin_claims_obligatorios_da_401(crear_app):
    app = crear_app(autenticado=False)
    sin_jti = jwt.encode(
        {"sub": AUTH_USUARIO, "iat": int(time.time()), "exp": int(time.time()) + 60},
        AUTH_SECRETO, algorithm="HS256",
    )

    resp = app.client.get("/eventos", headers={"Authorization": f"Bearer {sin_jti}"})

    assert resp.status_code == 401


def test_token_alg_none_da_401(crear_app):
    app = crear_app(autenticado=False)
    sin_firma = jwt.encode(
        {"sub": AUTH_USUARIO, "iat": 1, "exp": 9999999999, "jti": "x"}, None, algorithm="none"
    )

    resp = app.client.get("/eventos", headers={"Authorization": f"Bearer {sin_firma}"})

    assert resp.status_code == 401


def test_auth_me_devuelve_el_usuario(crear_app):
    app = crear_app()

    resp = app.client.get("/auth/me")

    assert resp.status_code == 200
    assert resp.json() == {"usuario": AUTH_USUARIO}
    assert _sin_token(app).get("/auth/me").status_code == 401


def test_health_es_publico_y_no_revela_detalles(crear_app):
    app = crear_app(autenticado=False)

    resp = app.client.get("/health")

    assert resp.status_code in (200, 503)
    assert set(resp.json()) == {"fog", "redis", "postgres"}
    assert set(resp.json().values()) <= {"ok", "error"}


PUBLICAS = {("GET", "/health"), ("POST", "/auth/login")}


def test_ninguna_ruta_responde_sin_token_salvo_health_y_login(crear_app):
    """Recorre `app.routes`: toda ruta distinta de /health y /auth/login debe
    rechazar la petición sin token (401). Una ruta nueva sin protección falla."""
    app = crear_app(autenticado=False)
    revisadas = 0

    for ruta in _rutas(app.fastapi):
        if isinstance(ruta, APIRoute):
            for metodo in ruta.methods - {"HEAD", "OPTIONS"}:
                if (metodo, ruta.path) in PUBLICAS:
                    continue
                url = ruta.path.replace("{", "").replace("}", "")
                resp = app.client.request(metodo, url)
                assert resp.status_code == 401, f"{metodo} {ruta.path} → {resp.status_code}"
                revisadas += 1
        elif isinstance(ruta, APIWebSocketRoute):
            from starlette.websockets import WebSocketDisconnect

            url = ruta.path.replace("{", "").replace("}", "")
            with pytest.raises(WebSocketDisconnect) as exc:
                with app.client.websocket_connect(url):
                    pass
            assert exc.value.code == 1008, ruta.path
            revisadas += 1
    assert revisadas >= 15  # el recorrido no quedó vacío


def test_websocket_acepta_token_en_query_y_rechaza_sin_token(crear_app):
    app = crear_app(autenticado=False)
    from starlette.websockets import WebSocketDisconnect

    token = encabezado_auth(app.container)["Authorization"].split()[1]

    # Con token válido pasa la autenticación y llega a la lógica de la ruta:
    # sin sesión activa rechaza el handshake con 404 (no con 1008 de auth).
    with pytest.raises(Exception) as sin_sesion:
        with app.client.websocket_connect(f"/ws/veredicto/x?token={token}"):
            pass
    with pytest.raises(WebSocketDisconnect) as sin_token:
        with app.client.websocket_connect("/ws/veredicto/x?token=malo"):
            pass
    assert getattr(sin_sesion.value, "status_code", None) == 404
    assert sin_token.value.code == 1008


# --- Token de proxy --------------------------------------------------------


def test_con_token_de_proxy_sin_cabecera_da_403(crear_app):
    app = crear_app(proxy_token="proxy-secreto")

    for ruta in ("/health", "/eventos", "/auth/me"):
        assert app.client.get(ruta).status_code == 403, ruta
    assert app.client.post("/auth/login", json=LOGIN).status_code == 403


def test_con_token_de_proxy_incorrecto_da_403(crear_app):
    app = crear_app(proxy_token="proxy-secreto")

    resp = app.client.get("/eventos", headers={"X-Proxy-Token": "otro"})

    assert resp.status_code == 403
    assert resp.json() == {"detail": "Acceso denegado"}


def test_con_token_de_proxy_y_jwt_da_200(crear_app):
    app = crear_app(proxy_token="proxy-secreto")

    resp = app.client.get("/eventos", headers={"X-Proxy-Token": "proxy-secreto"})

    assert resp.status_code == 200


def test_token_de_proxy_no_reemplaza_al_jwt(crear_app):
    app = crear_app(proxy_token="proxy-secreto", autenticado=False)

    resp = app.client.get("/eventos", headers={"X-Proxy-Token": "proxy-secreto"})

    assert resp.status_code == 401


def test_sin_token_de_proxy_configurado_no_se_exige(crear_app):
    app = crear_app()

    assert app.client.get("/eventos").status_code == 200


def test_la_403_del_proxy_lleva_cabeceras_de_seguridad(crear_app):
    app = crear_app(proxy_token="proxy-secreto")

    resp = app.client.get("/eventos")

    assert resp.status_code == 403
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_bloqueo_usa_x_forwarded_for_solo_tras_el_proxy(crear_app):
    """Con el proxy de confianza el bloqueo es por la IP reenviada: otra IP
    sigue pudiendo entrar. Sin proxy configurado, XFF se ignora."""
    cab = {"X-Proxy-Token": "proxy-secreto"}
    app = crear_app(proxy_token="proxy-secreto", autenticado=False)
    for _ in range(5):
        app.client.post("/auth/login", json=MALO, headers={**cab, "X-Forwarded-For": "1.1.1.1"})

    bloqueada = app.client.post("/auth/login", json=LOGIN, headers={**cab, "X-Forwarded-For": "1.1.1.1"})
    otra = app.client.post("/auth/login", json=LOGIN, headers={**cab, "X-Forwarded-For": "2.2.2.2"})
    assert bloqueada.status_code == 429
    assert otra.status_code == 200

    local = crear_app(autenticado=False)
    for _ in range(5):
        local.client.post("/auth/login", json=MALO, headers={"X-Forwarded-For": "3.3.3.3"})
    # Un cliente local no puede evitar el bloqueo cambiando XFF.
    evasion = local.client.post("/auth/login", json=LOGIN, headers={"X-Forwarded-For": "4.4.4.4"})
    assert evasion.status_code == 429


# --- CORS ------------------------------------------------------------------


def _preflight(app, origen: str):
    return app.client.options(
        "/matches/config",
        headers={
            "Origin": origen,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_preflight_de_origen_no_listado_no_recibe_allow_origin(crear_app):
    app = crear_app(cors_origins=["http://localhost:8081"])

    resp = _preflight(app, "https://malo.example")

    assert "access-control-allow-origin" not in resp.headers


def test_preflight_sin_lista_de_origenes_no_recibe_allow_origin(crear_app):
    app = crear_app()  # lista vacía: despliegue remoto, mismo origen

    assert "access-control-allow-origin" not in _preflight(app, "http://localhost:8081").headers


def test_preflight_de_origen_listado_es_estricto(crear_app):
    app = crear_app(cors_origins=["http://localhost:8081"])

    resp = _preflight(app, "http://localhost:8081")

    assert resp.headers["access-control-allow-origin"] == "http://localhost:8081"
    assert "access-control-allow-credentials" not in resp.headers
    assert resp.headers["access-control-allow-methods"] == "GET, POST, OPTIONS"
    permitidas = {h.strip() for h in resp.headers["access-control-allow-headers"].split(",")}
    assert {"Authorization", "Content-Type"} <= permitidas
    assert "*" not in permitidas


def test_cors_no_admite_comodin(crear_app):
    with pytest.raises(RuntimeError, match="comodines"):
        crear_app(cors_origins=["*"])


# --- Cabeceras y documentación ---------------------------------------------


@pytest.mark.parametrize("ruta", ["/health", "/auth/me", "/eventos", "/no-existe"])
def test_cabeceras_de_seguridad_en_toda_respuesta(crear_app, ruta):
    app = crear_app()

    h = app.client.get(ruta).headers

    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert h["cache-control"] == "no-store"


def test_cabeceras_de_seguridad_en_login_fallido(crear_app):
    app = crear_app(autenticado=False)

    resp = app.client.post("/auth/login", json=MALO)

    assert resp.status_code == 401
    assert resp.headers["cache-control"] == "no-store"


def test_docs_disponibles_en_local_y_404_en_remoto(crear_app):
    local = crear_app(entorno="local")
    remoto = crear_app(entorno="remoto", autenticado=False)

    assert local.client.get("/docs").status_code == 200
    for ruta in ("/docs", "/redoc", "/openapi.json"):
        assert remoto.client.get(ruta).status_code == 404, ruta


def test_websocket_no_existe_en_remoto(crear_app):
    app = crear_app(entorno="remoto")

    assert not any(isinstance(r, APIWebSocketRoute) for r in _rutas(app.fastapi))


# --- Registro --------------------------------------------------------------


def test_eventos_de_auth_se_registran_sin_secretos(crear_app, caplog):
    app = crear_app(autenticado=False)
    caplog.set_level(logging.INFO, logger="sabre.auth")

    for _ in range(5):
        app.client.post("/auth/login", json=MALO)
    app.client.get("/eventos", headers={"Authorization": "Bearer token-secreto-xyz"})
    app.container.limitador_intentos().registrar_exito  # noqa: B018 (solo existencia)
    texto = "\n".join(r.getMessage() for r in caplog.records)

    assert texto.count("auth.login_fallo") == 5
    assert "auth.bloqueo" in texto
    assert "auth.token_invalido" in texto
    assert AUTH_USUARIO in texto and "ip=testclient" in texto
    assert "otra-clave-incorrecta" not in texto
    assert "token-secreto-xyz" not in texto


def test_login_ok_se_registra(crear_app, caplog):
    app = crear_app(autenticado=False)
    caplog.set_level(logging.INFO, logger="sabre.auth")

    token = app.client.post("/auth/login", json=LOGIN).json()["access_token"]
    texto = "\n".join(r.getMessage() for r in caplog.records)

    assert "auth.login_ok" in texto
    assert AUTH_PASSWORD not in texto and token not in texto


def test_usuario_con_saltos_de_linea_no_inyecta_lineas_en_el_log(crear_app, caplog):
    app = crear_app(autenticado=False)
    caplog.set_level(logging.INFO, logger="sabre.auth")

    app.client.post("/auth/login", json={"usuario": "x\nauth.login_ok ip=9.9.9.9", "password": "y"})

    assert all("\n" not in r.getMessage() for r in caplog.records)
