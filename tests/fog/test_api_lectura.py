"""Endpoints de solo lectura: GET /revisiones, GET /revisiones/{id},
GET /auditoria/verificar, GET /modelo/activo y GET /health. App completa
contra PostgreSQL real (ver conftest.py: `crear_app`); una prueba de API
por endpoint más sus casos de borde."""

from __future__ import annotations

import uuid

from dependency_injector import providers

from fog.application.consultar_revisiones import ConsultarSalud
from fog.infrastructure.messaging.redis_sonda_salud import RedisSonda
from fog.ports.sonda_salud import SondaSaludPort


class SondaFalsa(SondaSaludPort):
    def __init__(self, responde: bool):
        self._responde = responde

    async def responde(self) -> bool:
        return self._responde


class _RedisCaido:
    async def ping(self):
        raise ConnectionError("Redis no responde")


def _evento_nuevo(app) -> str:
    return str(app.sql.escalar(
        "INSERT INTO sabre.evento (nombre, fecha, tipo) "
        "VALUES (:n, '2026-10-01', 'piloto') RETURNING id", n=f"E-{uuid.uuid4().hex[:8]}",
    ))


def _revision(app, evento_id: str | None = None) -> str:
    match_id = app.configurar(**({"evento_id": evento_id} if evento_id else {}))
    resp = app.subir_clip(match_id)
    assert resp.status_code == 200, resp.text
    return resp.json()["revision_id"]


# ---------------------------------------------------------------------------
# GET /revisiones
# ---------------------------------------------------------------------------

def test_get_revisiones_lista_resumen_filtra_y_ordena(crear_app):
    app = crear_app()
    evento_a, evento_b = _evento_nuevo(app), _evento_nuevo(app)
    primera = _revision(app, evento_a)
    segunda = _revision(app, evento_a)
    otra_del_evento_b = _revision(app, evento_b)
    assert app.veredicto(segunda, decision="cambiar", clase_final="ContrattackB").status_code == 200

    resp = app.client.get("/revisiones", params={"evento_id": evento_a})

    assert resp.status_code == 200
    filas = resp.json()
    assert [f["id"] for f in filas] == [segunda, primera]  # más reciente primero
    cerrada, abierta = filas
    assert set(cerrada) == {
        "id", "combate_id", "abierta_en", "cerrada_en", "disponible", "clase",
        "confianza", "decision", "clase_final",
    }
    assert (cerrada["disponible"], cerrada["clase"], cerrada["confianza"]) == (True, "AttackA", 0.74)
    assert (cerrada["decision"], cerrada["clase_final"]) == ("cambiar", "ContrattackB")
    assert cerrada["cerrada_en"] is not None
    assert (abierta["decision"], abierta["clase_final"], abierta["cerrada_en"]) == (None, None, None)
    assert otra_del_evento_b not in [f["id"] for f in filas]
    assert otra_del_evento_b in [f["id"] for f in app.client.get("/revisiones").json()]

    abierta_en = {f["id"]: f["abierta_en"] for f in filas}
    solo_segunda = app.client.get(
        "/revisiones", params={"evento_id": evento_a, "desde": abierta_en[segunda]}
    ).json()
    hasta_primera = app.client.get(
        "/revisiones", params={"evento_id": evento_a, "hasta": abierta_en[primera]}
    ).json()
    assert [f["id"] for f in solo_segunda] == [segunda]  # `desde` es inclusivo
    assert [f["id"] for f in hasta_primera] == [primera]  # `hasta` es inclusivo
    sin_zona = app.client.get(
        "/revisiones", params={"evento_id": evento_a, "hasta": "2000-01-01T00:00:00"}
    )
    assert sin_zona.status_code == 200 and sin_zona.json() == []  # sin zona = UTC


def test_get_revisiones_con_filtros_invalidos_responde_422(crear_app):
    app = crear_app()

    assert app.client.get("/revisiones", params={"evento_id": "no-es-uuid"}).status_code == 422
    assert app.client.get("/revisiones", params={"desde": "ayer"}).status_code == 422


# ---------------------------------------------------------------------------
# GET /revisiones/{id}
# ---------------------------------------------------------------------------

def test_get_revision_devuelve_sugerencia_decision_y_hash(crear_app):
    app = crear_app()
    revision_id = _revision(app)

    abierta = app.client.get(f"/revisiones/{revision_id}")

    assert abierta.status_code == 200
    d = abierta.json()
    assert set(d) == {
        "id", "combate_id", "abierta_en", "cerrada_en", "sugerencia", "probabilidades",
        "decision", "clase_final", "registrado_en", "auditoria_seq", "auditoria_hash",
    }
    assert d["sugerencia"] == {
        "disponible": True, "motivo_no_disp": None, "clase": "AttackA",
        "tirador": "A", "confianza": 0.74,
    }
    assert d["probabilidades"]["ContrattackA"] == 0.16  # vocabulario del modelo
    assert set(d["probabilidades"]) == {
        "AttackA", "AttackB", "ContrattackA", "ContrattackB", "RiposteA", "RiposteB",
    }
    assert all(d[k] is None for k in (
        "cerrada_en", "decision", "clase_final", "registrado_en", "auditoria_seq", "auditoria_hash",
    ))

    registrado = app.veredicto(revision_id, decision="cambiar", clase_final="RiposteB").json()
    cerrada = app.client.get(f"/revisiones/{revision_id}").json()

    assert (cerrada["decision"], cerrada["clase_final"]) == ("cambiar", "RiposteB")
    assert cerrada["registrado_en"] == registrado["registrado_en"]
    assert cerrada["cerrada_en"] == registrado["cerrada_en"]
    assert cerrada["auditoria_seq"] == registrado["auditoria_seq"]
    assert cerrada["auditoria_hash"] == registrado["auditoria_hash"]
    assert cerrada["sugerencia"]["clase"] == "AttackA"  # la sugerencia original no cambia


def test_get_revision_sin_clasificacion_disponible_muestra_el_motivo(crear_app):
    app = crear_app(extraccion_falla=True)
    revision_id = _revision(app)

    d = app.client.get(f"/revisiones/{revision_id}").json()

    assert d["sugerencia"] == {
        "disponible": False, "motivo_no_disp": "pose_incompleta",
        "clase": None, "tirador": None, "confianza": None,
    }
    assert d["probabilidades"] is None


def test_get_revision_inexistente_o_no_uuid_responde_404(crear_app):
    app = crear_app()

    assert app.client.get(f"/revisiones/{uuid.uuid4()}").status_code == 404
    assert app.client.get("/revisiones/no-es-uuid").status_code == 404


# ---------------------------------------------------------------------------
# GET /auditoria/verificar
# ---------------------------------------------------------------------------

def test_get_auditoria_verificar_detecta_registros_alterados(crear_app):
    app = crear_app()
    revision_id = _revision(app)
    assert app.veredicto(revision_id).status_code == 200

    integra = app.client.get("/auditoria/verificar")

    assert integra.status_code == 200
    assert integra.json() == {"integra": True, "alteradas": []}

    # Se altera el snapshot saltando el trigger de inmutabilidad (solo la
    # prueba puede hacerlo: la API no expone escritura).
    app.sql.ejecutar("ALTER TABLE sabre.registro_auditoria DISABLE TRIGGER tg_auditoria_inmutable")
    try:
        app.sql.ejecutar(
            "UPDATE sabre.registro_auditoria SET snapshot = snapshot || '{\"x\": 1}'::jsonb "
            "WHERE revision_id = :r", r=revision_id,
        )
        alterada = app.client.get("/auditoria/verificar")
    finally:
        app.sql.ejecutar("ALTER TABLE sabre.registro_auditoria ENABLE TRIGGER tg_auditoria_inmutable")

    assert alterada.status_code == 200
    cuerpo = alterada.json()
    assert cuerpo["integra"] is False
    seq = app.client.get(f"/revisiones/{revision_id}").json()["auditoria_seq"]
    fila = next(a for a in cuerpo["alteradas"] if a["seq"] == seq)
    assert set(fila) == {"seq", "esperado", "guardado"}
    assert fila["esperado"] != fila["guardado"]


# ---------------------------------------------------------------------------
# GET /modelo/activo
# ---------------------------------------------------------------------------

def test_get_modelo_activo_devuelve_nombre_clases_y_metricas(crear_app):
    app = crear_app()
    app.sql.ejecutar(
        "UPDATE sabre.modelo_version SET f1_macro_test = 0.4856, kappa_piloto = NULL "
        "WHERE activo"
    )

    resp = app.client.get("/modelo/activo")

    assert resp.status_code == 200
    activo = app.sql.filas("SELECT nombre FROM sabre.modelo_version WHERE activo")[0]
    assert resp.json() == {
        "nombre": activo["nombre"], "num_clases": 6, "f1_macro_test": 0.4856, "kappa_piloto": None,
    }


def test_get_modelo_activo_sin_version_activa_responde_404(crear_app):
    app = crear_app()
    activo = app.sql.escalar("SELECT id FROM sabre.modelo_version WHERE activo")
    app.sql.ejecutar("UPDATE sabre.modelo_version SET activo = FALSE WHERE id = :i", i=activo)
    try:
        resp = app.client.get("/modelo/activo")
    finally:
        app.sql.ejecutar("UPDATE sabre.modelo_version SET activo = TRUE WHERE id = :i", i=activo)

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

def _sondas(app, *, redis: bool, postgres: bool) -> None:
    """`consultar_salud` es Singleton: se reemplaza entero para cambiar las sondas."""
    app.container.consultar_salud.override(
        providers.Object(ConsultarSalud(SondaFalsa(redis), SondaFalsa(postgres)))
    )


def test_get_health_reporta_fog_redis_y_postgres(crear_app):
    app = crear_app()

    _sondas(app, redis=True, postgres=True)
    ok = app.client.get("/health")
    assert ok.status_code == 200
    assert ok.json() == {"fog": "ok", "redis": "ok", "postgres": "ok"}

    _sondas(app, redis=False, postgres=True)
    sin_redis = app.client.get("/health")
    assert sin_redis.status_code == 503
    assert sin_redis.json() == {"fog": "ok", "redis": "error", "postgres": "ok"}

    _sondas(app, redis=True, postgres=False)
    sin_postgres = app.client.get("/health")
    assert sin_postgres.status_code == 503
    assert sin_postgres.json() == {"fog": "ok", "redis": "ok", "postgres": "error"}


def test_health_usa_la_sonda_real_de_postgres_y_la_de_redis_caida(crear_app):
    """Sin doblar la sonda de Postgres: la base de pruebas responde; Redis
    (cliente real sin servidor) se reporta caído en vez de colgar el endpoint."""
    app = crear_app()
    app.container.sonda_redis.override(providers.Object(RedisSonda(_RedisCaido())))

    resp = app.client.get("/health")

    assert resp.status_code == 503
    assert resp.json() == {"fog": "ok", "redis": "error", "postgres": "ok"}


def test_los_endpoints_de_lectura_no_aceptan_escritura(crear_app):
    app = crear_app()
    rutas = ["/revisiones", f"/revisiones/{uuid.uuid4()}", "/auditoria/verificar",
             "/modelo/activo", "/health"]

    for ruta in rutas:
        assert app.client.post(ruta, json={}).status_code in (404, 405, 422)
        assert app.client.delete(ruta).status_code in (404, 405)
