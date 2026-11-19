"""Brazo armado obligatorio (docs_claude/contexto_sabre.md sección 8): 41/104
clips de test tienen al menos un tirador zurdo, así que no se analiza un
clip sin brazo declarado para ambos tiradores ni con valor por defecto.

- weapon_side_A/B obligatorios, sin default, en POST /matches/config (422 si falta alguno).
- SessionRegistry.get_or_create_default eliminado: el clip responde 404 si el
  combate no fue creado.
"""

import uuid

import pytest

from fog.infrastructure.sesiones.session_registry import SessionRegistry


@pytest.mark.parametrize("lado", ["A", "B"])
def test_configurar_sin_brazo_responde_422_y_no_crea_combate(crear_app, lado):
    app = crear_app()
    antes = app.sql.escalar("SELECT count(*) FROM sabre.combate")
    body = app.body_config()
    del body[f"weapon_side_{lado}"]

    resp = app.client.post("/matches/config", json=body)

    assert resp.status_code == 422
    assert app.sql.escalar("SELECT count(*) FROM sabre.combate") == antes


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


def test_la_sesion_de_cada_clip_toma_el_brazo_armado_del_combate_guardado(crear_app):
    """El combate vive en la base: cada clip crea su sesión con el brazo
    armado guardado, sin caer en ningún valor por defecto."""
    app = crear_app()
    match_id = app.configurar(weapon_side_A="left", weapon_side_B="right")

    resp = app.subir_clip(match_id)

    assert resp.status_code == 200, resp.text
    sesion = app.container.sessions().get(resp.json()["revision_id"])
    assert (sesion.weapon_side_a.value, sesion.weapon_side_b.value) == ("left", "right")
    extractor = app.container.feature_extractor()
    _tracked, lado_a, lado_b, _min = extractor.calls[0]
    assert (lado_a.value, lado_b.value) == ("left", "right")
