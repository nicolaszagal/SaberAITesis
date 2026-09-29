"""Brazo armado obligatorio (docs_claude/contexto_sabre.md sección 8): 41/104
clips de test tienen al menos un tirador zurdo, así que no se analiza un
clip sin brazo declarado para ambos tiradores ni con valor por defecto.

- weapon_side_A/B obligatorios, sin default, en POST /matches/config y en
  POST /webrtc/offer (422 si falta alguno).
- SessionRegistry.get_or_create_default eliminado: clip, luz y WebSocket
  responden 404 si el combate no fue creado.
"""

import uuid

import pytest
from starlette.testclient import WebSocketDenialResponse

from fog.infrastructure.webrtc.session_registry import SessionRegistry


@pytest.mark.parametrize("lado", ["A", "B"])
def test_configurar_sin_brazo_responde_422_y_no_crea_combate(crear_app, lado):
    app = crear_app()
    antes = app.sql.escalar("SELECT count(*) FROM sabre.combate")
    body = app.body_config()
    del body[f"weapon_side_{lado}"]

    resp = app.client.post("/matches/config", json=body)

    assert resp.status_code == 422
    assert app.sql.escalar("SELECT count(*) FROM sabre.combate") == antes


@pytest.mark.parametrize("lado", ["A", "B"])
def test_offer_sin_brazo_responde_422(crear_app, lado):
    app = crear_app()
    body = {"sdp": "v=0", "type": "offer", "weapon_side_A": "right", "weapon_side_B": "left"}
    del body[f"weapon_side_{lado}"]

    resp = app.client.post("/webrtc/offer", json=body)

    assert resp.status_code == 422
    assert f"weapon_side_{lado}" in resp.text


def test_offer_con_brazo_invalido_responde_422(crear_app):
    app = crear_app()
    body = {"sdp": "v=0", "type": "offer", "weapon_side_A": "zurdo", "weapon_side_B": "left"}

    assert app.client.post("/webrtc/offer", json=body).status_code == 422


def test_session_registry_ya_no_crea_sesiones_por_defecto():
    assert not hasattr(SessionRegistry, "get_or_create_default")


def test_clip_sin_combate_configurado_responde_404(crear_app):
    app = crear_app()
    clips_antes = app.sql.escalar("SELECT count(*) FROM sabre.clip")

    resp = app.subir_clip(str(uuid.uuid4()))

    assert resp.status_code == 404
    assert app.sql.escalar("SELECT count(*) FROM sabre.clip") == clips_antes
    assert app.container.feature_publisher().published == []


def test_clip_con_match_id_que_no_es_uuid_responde_404(crear_app):
    app = crear_app()

    assert app.subir_clip("m-inventado").status_code == 404


def test_luz_sin_combate_configurado_responde_404(crear_app):
    app = crear_app()

    resp = app.client.post(
        f"/webrtc/{uuid.uuid4()}/luz", json={"has_luz_A": True, "has_luz_B": False}
    )

    assert resp.status_code == 404


def test_websocket_sin_combate_configurado_responde_404(crear_app):
    app = crear_app()

    with pytest.raises(WebSocketDenialResponse) as exc:
        with app.client.websocket_connect(f"/ws/veredicto/{uuid.uuid4()}"):
            pass

    assert exc.value.status_code == 404


def test_luz_y_websocket_funcionan_con_combate_configurado(crear_app):
    app = crear_app()
    match_id = app.configurar()

    resp = app.client.post(f"/webrtc/{match_id}/luz", json={"has_luz_A": True, "has_luz_B": False})

    assert resp.status_code == 200
    assert resp.json()["has_luz_A"] is True


def test_sesion_liberada_se_reconstruye_desde_el_combate_guardado(crear_app):
    """El combate vive en la base: si la sesión en memoria ya se liberó (TTL
    o reinicio de Fog), luz y clip siguen funcionando con el brazo armado
    guardado, sin caer en ningún valor por defecto."""
    app = crear_app()
    match_id = app.configurar(weapon_side_A="left", weapon_side_B="right")
    app.container.sessions().remove(match_id)

    resp = app.subir_clip(match_id)

    assert resp.status_code == 200, resp.text
    sesion = app.container.sessions().get(match_id)
    assert (sesion.weapon_side_a.value, sesion.weapon_side_b.value) == ("left", "right")
    extractor = app.container.feature_extractor()
    _tracked, lado_a, lado_b, _min = extractor.calls[0]
    assert (lado_a.value, lado_b.value) == ("left", "right")
