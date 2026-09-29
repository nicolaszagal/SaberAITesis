"""GET /matches/{match_id} (F-039): el frontend valida con él el combate activo
que recuerda entre recargas. App completa contra PostgreSQL real (ver
conftest.py: `crear_app`)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI

from fog.infrastructure.api import routes


def test_get_combate_devuelve_pista_arbitro_alias_y_brazo_de_a_y_b(crear_app):
    app = crear_app()
    match_id = app.configurar(alias_A="Rojo", weapon_side_A="right", alias_B="Verde", weapon_side_B="left")

    resp = app.client.get(f"/matches/{match_id}")

    assert resp.status_code == 200
    nombre_arbitro = app.sql.filas(
        "SELECT nombre FROM sabre.usuario WHERE id = :i", i=app.arbitro_id
    )[0]["nombre"]
    assert resp.json() == {
        "match_id": match_id,
        "pista": "P1",
        "arbitro_id": str(app.arbitro_id),
        "arbitro": nombre_arbitro,
        "alias_A": "Rojo",
        "weapon_side_A": "right",
        "alias_B": "Verde",
        "weapon_side_B": "left",
    }


def test_get_combate_inexistente_o_no_uuid_responde_404(crear_app):
    app = crear_app()

    assert app.client.get(f"/matches/{uuid.uuid4()}").status_code == 404
    assert app.client.get("/matches/no-es-uuid").status_code == 404


def test_get_combate_no_acepta_escritura(crear_app):
    app = crear_app()
    match_id = app.configurar()

    assert app.client.put(f"/matches/{match_id}", json={}).status_code in (404, 405)
    assert app.client.delete(f"/matches/{match_id}").status_code in (404, 405)


def test_get_combate_esta_documentado_como_solo_lectura():
    app = FastAPI()
    app.include_router(routes.router)

    assert set(app.openapi()["paths"]["/matches/{match_id}"]) == {"get"}
