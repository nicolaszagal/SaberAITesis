"""Swagger (/openapi.json) refleja el contrato de revisiones por clip.

No necesita base ni contenedor: solo genera el esquema OpenAPI del router.
"""

from fastapi import FastAPI

from fog.infrastructure.api import routes


def _openapi() -> dict:
    app = FastAPI()
    app.include_router(routes.router)
    return app.openapi()


def test_rutas_de_revisiones_y_catalogos_estan_documentadas():
    paths = _openapi()["paths"]

    assert "post" in paths["/revisiones/{revision_id}/veredicto"]
    assert "get" in paths["/eventos"]
    assert "get" in paths["/usuarios"]
    assert "post" in paths["/matches/{match_id}/clip"]


def test_la_ruta_de_veredicto_por_combate_no_esta_documentada():
    assert "/matches/{match_id}/veredicto" not in _openapi()["paths"]


def test_los_catalogos_son_de_solo_lectura():
    paths = _openapi()["paths"]

    assert set(paths["/eventos"]) == {"get"}
    assert set(paths["/usuarios"]) == {"get"}


def test_usuarios_documenta_el_filtro_de_rol():
    parametros = _openapi()["paths"]["/usuarios"]["get"]["parameters"]

    rol = next(p for p in parametros if p["name"] == "rol")
    assert rol["required"] is False
    opciones = rol["schema"]["anyOf"][0]["enum"]
    assert opciones == ["arbitro", "operador", "administrador"]


def test_las_respuestas_del_clip_y_de_la_oferta_incluyen_revision_id():
    schemas = _openapi()["components"]["schemas"]

    assert "revision_id" in schemas["ClipUploadResponse"]["properties"]
    assert "revision_id" in schemas["OfferResponse"]["properties"]
    assert "revision_id" in schemas["VeredictoResponse"]["properties"]


def test_clase_final_usa_los_nombres_del_modelo_y_se_documenta_como_obligatoria_con_mantener_y_cambiar():
    request = _openapi()["components"]["schemas"]["VeredictoRequest"]["properties"]["clase_final"]

    opciones = request["anyOf"][0]["enum"]
    assert opciones == ["AttackA", "AttackB", "ContrattackA", "ContrattackB", "RiposteA", "RiposteB"]
    assert "mantener" in request["description"] and "cambiar" in request["description"]


def test_el_clip_ya_no_documenta_409():
    respuestas = _openapi()["paths"]["/matches/{match_id}/clip"]["post"]["responses"]

    assert "409" not in respuestas
    assert "422" in respuestas


def test_los_endpoints_de_lectura_estan_documentados_y_son_solo_get():
    paths = _openapi()["paths"]

    assert set(paths["/revisiones"]) == {"get"}
    assert set(paths["/revisiones/{revision_id}"]) == {"get"}
    for ruta in ("/auditoria/verificar", "/modelo/activo", "/health"):
        assert set(paths[ruta]) == {"get"}
