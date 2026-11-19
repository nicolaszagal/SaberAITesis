"""Combate activo explícito y token de servicio de Edge (EDGE02, decisiones del 18/11/2026)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from fog.infrastructure.persistence.combate_activo_archivo import CombateActivoArchivo
from shared import config
from tests.fog.conftest import clip_de_prueba

TOKEN = "t" * 64


def _cliente(app, host="127.0.0.1", headers=None):
    """Cliente sin JWT que simula la IP del socket de la petición."""
    return TestClient(app.fastapi, client=(host, 50000), raise_server_exceptions=False, headers=headers)


def _subir(cliente, match_id, headers=None):
    return cliente.post(
        f"/matches/{match_id}/tocados",
        files={"file": ("t.mp4", clip_de_prueba(), "video/mp4")}, data={"t_luz_a_ms": "300"}, headers=headers,
    )


# ------------------------------------------------------------------ combate activo


def test_sin_combate_configurado_no_hay_activo(crear_app):
    app = crear_app()
    assert app.client.get("/matches/activo").status_code == 404


def test_configurar_marca_el_combate_como_activo_y_el_siguiente_lo_reemplaza(crear_app):
    app = crear_app()
    primero = app.configurar()
    assert app.client.get("/matches/activo").json() == {"match_id": primero}
    segundo = app.configurar()
    assert segundo != primero
    assert app.client.get("/matches/activo").json() == {"match_id": segundo}


def test_el_activo_no_se_deduce_de_la_fecha_de_creacion(crear_app):
    """Un combate creado por otra vía (más reciente en la base) no pasa a ser el activo."""
    app = crear_app()
    activo = app.configurar()
    app.sql.ejecutar(
        "INSERT INTO sabre.tirador (alias, brazo_habitual, es_menor) VALUES ('x1', 'diestro', FALSE), ('x2', 'zurdo', FALSE)")
    app.sql.ejecutar(
        "INSERT INTO sabre.combate (pista, tirador_a_id, tirador_b_id, brazo_a, brazo_b, arbitro_id, configurado_por) "
        "SELECT 'PX', a.id, b.id, 'diestro', 'zurdo', :u, :u FROM sabre.tirador a, sabre.tirador b "
        "WHERE a.alias = 'x1' AND b.alias = 'x2'", u=app.arbitro_id)
    assert app.client.get("/matches/activo").json() == {"match_id": activo}


def test_el_activo_sobrevive_a_un_reinicio_de_fog(crear_app):
    app = crear_app()
    match_id = app.configurar()
    assert CombateActivoArchivo(app.storage_dir).obtener() == uuid.UUID(match_id)


# ------------------------------------------------------------------ token de servicio


@pytest.fixture
def con_token(monkeypatch):
    monkeypatch.setattr(config, "EDGE_TOKEN", TOKEN)


def test_edge_con_su_token_desde_loopback_usa_las_rutas_de_tocados(crear_app, con_token):
    app_jwt = crear_app()
    match_id = app_jwt.configurar()
    edge = _cliente(app_jwt, headers={"X-Edge-Token": TOKEN})
    r = edge.get("/matches/activo")
    assert r.status_code == 200 and r.json() == {"match_id": match_id}
    assert _subir(edge, match_id).status_code == 200


def test_token_equivocado_o_ausente_en_el_servidor_da_401(crear_app, monkeypatch):
    app = crear_app()
    match_id = app.configurar()
    monkeypatch.setattr(config, "EDGE_TOKEN", TOKEN)
    malo = _cliente(app, headers={"X-Edge-Token": "x" * 64})
    assert malo.get("/matches/activo").status_code == 401
    assert _subir(malo, match_id).status_code == 401
    monkeypatch.setattr(config, "EDGE_TOKEN", None)  # Fog sin token configurado: nada lo acepta
    assert _cliente(app, headers={"X-Edge-Token": TOKEN}).get("/matches/activo").status_code == 401
    assert _cliente(app, headers={"X-Edge-Token": ""}).get("/matches/activo").status_code == 401


def test_el_token_no_vale_desde_otra_ip_ni_detras_del_proxy(crear_app, con_token):
    app = crear_app()
    match_id = app.configurar()
    remoto = _cliente(app, host="10.8.0.7", headers={"X-Edge-Token": TOKEN})
    assert remoto.get("/matches/activo").status_code == 401
    assert _subir(remoto, match_id).status_code == 401
    # misma IP de loopback pero reenviada por el proxy (lleva X-Forwarded-For): tampoco
    proxy = _cliente(app, headers={"X-Edge-Token": TOKEN, "X-Forwarded-For": "203.0.113.9"})
    assert proxy.get("/matches/activo").status_code == 401
    assert _subir(proxy, match_id).status_code == 401


def test_el_token_solo_vale_en_las_rutas_de_tocados(crear_app, con_token):
    app = crear_app()
    match_id = app.configurar()
    edge = _cliente(app, headers={"X-Edge-Token": TOKEN})
    tocado = str(uuid.uuid4())
    for metodo, ruta in [
        ("get", f"/matches/{match_id}"),
        ("get", f"/matches/{match_id}/tocados"),
        ("post", f"/tocados/{tocado}/revision"),
        ("post", f"/tocados/{tocado}/decision-pista"),
        ("get", f"/tocados/{tocado}/clip"),
        ("get", "/edge/estado"),
        ("post", "/edge/senal-prueba"),
        ("get", "/revisiones"),
        ("post", "/matches/config"),
        ("post", "/sesion/cerrar"),
    ]:
        r = getattr(edge, metodo)(ruta)
        assert r.status_code == 401, f"{metodo.upper()} {ruta} aceptó el token de Edge ({r.status_code})"


def test_el_jwt_del_operador_sigue_valiendo_en_las_rutas_de_tocados(crear_app, con_token):
    app = crear_app()
    match_id = app.configurar()
    assert app.client.get("/matches/activo").status_code == 200
    assert _subir(app.client, match_id).status_code == 200


def test_sin_jwt_ni_token_las_rutas_de_tocados_dan_401(crear_app, con_token):
    app = crear_app()
    match_id = app.configurar()
    sin = _cliente(app)
    assert sin.get("/matches/activo").status_code == 401
    assert _subir(sin, match_id).status_code == 401
