"""D03 — flujo auditable de la revisión VAR, de punta a punta con TestClient
y PostgreSQL real (ver conftest.py: `crear_app`).

Cubre: POST /matches/config (CU-01), POST /matches/{id}/clip (CU-02, CU-03,
CU-05, CU-06), POST /revisiones/{id}/veredicto (CU-10, CU-11), la cadena de
auditoría (`fn_verificar_auditoria`), inmutabilidad (RNF-05) y los errores
409/422/404. El brazo armado obligatorio (contexto_sabre.md sección 8) se
prueba en test_brazo_armado_obligatorio.py.
"""

import asyncio
import json
import uuid

import numpy as np
import pytest
from sqlalchemy.exc import DBAPIError

from fog.domain.models import (
    MotivoNoDisponible,
    UnavailableResult,
    VerdictView,
)
from tests.fog.conftest import VEREDICTO_DEFAULT, clip_de_prueba, sha256_de
from tests.fog.fakes import FakeVerdictSubscriber

SQL_VEREDICTOS_DEL_COMBATE = (
    "SELECT count(*) FROM sabre.veredicto v JOIN sabre.revision_var r ON r.id = v.revision_id "
    "JOIN sabre.tocado t ON t.id = r.tocado_id WHERE t.combate_id = :i"
)
SQL_REVISIONES_ABIERTAS_DEL_COMBATE = (
    "SELECT count(*) FROM sabre.revision_var r JOIN sabre.tocado t ON t.id = r.tocado_id "
    "WHERE t.combate_id = :i AND r.cerrada_en IS NULL"
)


def _sin_filas_alteradas(app) -> None:
    assert app.sql.filas("SELECT * FROM sabre.fn_verificar_auditoria()") == []


def _combate_completo(app, **form) -> tuple[str, dict]:
    match_id = app.configurar()
    resp = app.subir_clip(match_id, **form)
    assert resp.status_code == 200, resp.text
    return match_id, resp.json()


def test_flujo_completo_persiste_y_audita(crear_app):
    app = crear_app()
    clip = clip_de_prueba(n_frames=5)

    # CU-01: combate con tiradores por alias y brazo armado traducido
    match_id = app.configurar()
    combate = app.sql.filas("SELECT * FROM sabre.combate WHERE id = :i", i=match_id)[0]
    assert (combate["brazo_a"], combate["brazo_b"]) == ("diestro", "zurdo")
    assert combate["pista"] == "P1"
    assert str(combate["evento_id"]) == str(app.evento_id)
    assert combate["arbitro_id"] == combate["configurado_por"] == app.arbitro_id
    aliases = app.sql.filas(
        "SELECT alias, brazo_habitual FROM sabre.tirador WHERE id IN (:a, :b) ORDER BY alias",
        a=combate["tirador_a_id"], b=combate["tirador_b_id"],
    )
    assert [(t["alias"], t["brazo_habitual"]) for t in aliases] == [
        ("Rojo", "diestro"), ("Verde", "zurdo"),
    ]

    # CU-02/03/05/06: clip + tocado + revisión + clasificación
    resp = app.subir_clip(match_id, clip=clip, has_luz_A="true", has_luz_B="true", t_tocado_ms="300")
    assert resp.status_code == 200, resp.text
    assert resp.json()["disponible"] is True
    assert resp.json()["action"] == "AttackA"
    revision_id = resp.json()["revision_id"]

    fila_clip = app.sql.filas("SELECT * FROM sabre.clip WHERE combate_id = :i", i=match_id)[0]
    assert fila_clip["origen"] == "carga"
    assert fila_clip["camara"] == "unica"
    assert (fila_clip["ancho_px"], fila_clip["alto_px"]) == (64, 64)
    assert float(fila_clip["fps"]) == 10.0
    assert fila_clip["duracion_ms"] == 500
    ruta_clip = app.storage_dir / fila_clip["uri"].removeprefix("local://")
    assert fila_clip["sha256"] == sha256_de(ruta_clip)
    assert ruta_clip.read_bytes() == clip

    tocado = app.sql.filas("SELECT * FROM sabre.tocado WHERE combate_id = :i", i=match_id)[0]
    assert tocado["fuente"] == "simulado"
    assert (tocado["luz_a"], tocado["luz_b"], tocado["t_tocado_ms"]) == (True, True, 300)
    vinculo = app.sql.filas("SELECT * FROM sabre.tocado_clip WHERE tocado_id = :t", t=tocado["id"])[0]
    assert vinculo["frame_tocado"] == 3  # round(0.300 s · 10 fps)

    revision = app.sql.filas("SELECT * FROM sabre.revision_var WHERE tocado_id = :t", t=tocado["id"])[0]
    assert str(revision["id"]) == revision_id
    assert revision["aceptada"] is True
    assert revision["arbitro_id"] == app.arbitro_id
    assert revision["cerrada_en"] is None  # sin veredicto no se cierra (RF-21)

    clasif = app.sql.filas("SELECT * FROM sabre.clasificacion WHERE tocado_id = :t", t=tocado["id"])[0]
    assert revision["clasificacion_id"] == clasif["id"]
    assert clasif["disponible"] is True
    assert (clasif["clase"], clasif["tirador"]) == ("AtaqueA", "A")
    assert float(clasif["confianza"]) == pytest.approx(0.74)
    assert clasif["probabilidades"]["ContraataqueA"] == pytest.approx(0.16)
    assert clasif["latencia_ms"] >= 0
    activo = app.sql.escalar("SELECT id FROM sabre.modelo_version WHERE activo")
    assert clasif["modelo_version_id"] == activo
    ruta_kp = app.storage_dir / clasif["keypoints_uri"].removeprefix("local://")
    assert clasif["keypoints_sha256"] == sha256_de(ruta_kp)
    with np.load(ruta_kp) as npz:
        assert {"a_xy", "b_xy", "a_conf", "a_box", "a_detected", "locked"} <= set(npz.files)

    # CU-10/11: veredicto que cambia la clase; todo en una transacción
    resp = app.veredicto(revision_id, decision="cambiar", clase_final="ContraataqueB")
    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["match_id"] == match_id
    assert cuerpo["revision_id"] == revision_id
    assert cuerpo["decision"] == "cambiar"
    assert cuerpo["clase_final"] == "ContraataqueB"
    assert cuerpo["cerrada_en"] == cuerpo["registrado_en"]

    revision = app.sql.filas("SELECT * FROM sabre.revision_var WHERE id = :i", i=revision["id"])[0]
    assert revision["cerrada_en"] is not None
    auditoria = app.sql.filas(
        "SELECT * FROM sabre.registro_auditoria WHERE revision_id = :i", i=revision["id"]
    )[0]
    snap = auditoria["snapshot"]
    assert set(snap) == {"revision", "tocado", "clasificacion", "veredicto", "modelo", "reglamento"}
    assert snap["reglamento"] == "FIE 2026"
    assert snap["veredicto"]["decision"] == "cambiar"
    assert snap["clasificacion"]["clase"] == "AtaqueA"
    assert snap["modelo"]["nombre"] == app.sql.escalar(
        "SELECT nombre FROM sabre.modelo_version WHERE activo"
    )
    assert snap["modelo"]["id"] == str(clasif["modelo_version_id"])
    assert snap["revision"]["cerrada_en"] is not None
    assert cuerpo["auditoria_hash"] == auditoria["hash"]

    _sin_filas_alteradas(app)


def test_modificar_veredicto_o_auditoria_falla(crear_app):
    app = crear_app()
    match_id, clip = _combate_completo(app)
    revision_id = clip["revision_id"]
    assert app.veredicto(revision_id).status_code == 200

    with pytest.raises(DBAPIError, match="no pueden modificarse"):
        app.sql.ejecutar("UPDATE sabre.veredicto SET decision = 'anular'")
    with pytest.raises(DBAPIError, match="no pueden modificarse"):
        app.sql.ejecutar("DELETE FROM sabre.veredicto")
    with pytest.raises(DBAPIError, match="no pueden modificarse"):
        app.sql.ejecutar("UPDATE sabre.registro_auditoria SET snapshot = '{}'::jsonb")
    _sin_filas_alteradas(app)


def test_segundo_veredicto_responde_409(crear_app):
    app = crear_app()
    match_id, clip = _combate_completo(app)
    revision_id = clip["revision_id"]
    assert app.veredicto(revision_id, decision="mantener").status_code == 200

    resp = app.veredicto(revision_id, decision="anular")

    assert resp.status_code == 409
    assert app.sql.escalar(
        "SELECT count(*) FROM sabre.veredicto v JOIN sabre.revision_var r ON r.id = v.revision_id "
        "JOIN sabre.tocado t ON t.id = r.tocado_id WHERE t.combate_id = :i", i=match_id,
    ) == 1


def test_cambiar_sin_clase_final_responde_422_y_no_cierra_la_revision(crear_app):
    app = crear_app()
    match_id, clip = _combate_completo(app)
    revision_id = clip["revision_id"]

    resp = app.veredicto(revision_id, decision="cambiar", clase_final=None)

    assert resp.status_code == 422
    assert app.sql.escalar(
        "SELECT count(*) FROM sabre.revision_var r JOIN sabre.tocado t ON t.id = r.tocado_id "
        "WHERE t.combate_id = :i AND r.cerrada_en IS NULL", i=match_id,
    ) == 1


def test_mantener_sin_clase_final_responde_422_y_no_cierra_la_revision(crear_app):
    app = crear_app()
    match_id, clip = _combate_completo(app)
    revision_id = clip["revision_id"]

    resp = app.veredicto(revision_id, decision="mantener", clase_final=None)

    assert resp.status_code == 422
    assert app.sql.escalar(SQL_REVISIONES_ABIERTAS_DEL_COMBATE, i=match_id) == 1
    assert app.sql.escalar(SQL_VEREDICTOS_DEL_COMBATE, i=match_id) == 0


def test_mantener_y_cambiar_registran_la_clase_final_declarada(crear_app):
    """`mantener`/`cambiar` describen la relación con la decisión original en
    pista; `clase_final` es siempre la decisión final declarada, aunque
    `mantener` no coincida con la clase sugerida."""
    app = crear_app()
    _, primero = _combate_completo(app)
    _, segundo = _combate_completo(app)

    r1 = app.veredicto(primero["revision_id"], decision="mantener", clase_final="RiposteB")
    r2 = app.veredicto(segundo["revision_id"], decision="cambiar", clase_final="ContraataqueA")

    assert (r1.status_code, r2.status_code) == (200, 200)
    assert (r1.json()["decision"], r1.json()["clase_final"]) == ("mantener", "RiposteB")
    assert (r2.json()["decision"], r2.json()["clase_final"]) == ("cambiar", "ContraataqueA")
    guardadas = app.sql.filas(
        "SELECT decision, clase_final FROM sabre.veredicto WHERE revision_id = ANY(:ids)",
        ids=[uuid.UUID(primero["revision_id"]), uuid.UUID(segundo["revision_id"])],
    )
    assert {(g["decision"], g["clase_final"]) for g in guardadas} == {
        ("mantener", "RiposteB"), ("cambiar", "ContraataqueA"),
    }


def test_anular_con_clase_final_responde_422(crear_app):
    app = crear_app()
    match_id, clip = _combate_completo(app)
    revision_id = clip["revision_id"]

    assert app.veredicto(revision_id, decision="anular", clase_final="AtaqueA").status_code == 422


def test_clase_final_fuera_del_dominio_responde_422(crear_app):
    app = crear_app()
    match_id, clip = _combate_completo(app)
    revision_id = clip["revision_id"]

    assert app.veredicto(revision_id, decision="cambiar", clase_final="AttackA").status_code == 422


def test_veredicto_es_atomico_si_falla_la_auditoria(crear_app, monkeypatch):
    """Si el registro de auditoría falla, no queda veredicto ni revisión
    cerrada (una sola transacción)."""
    from fog.infrastructure.persistence.postgres.auditoria_repository import (
        PostgresAuditoriaRepository,
    )

    app = crear_app()
    match_id, clip = _combate_completo(app)
    revision_id = clip["revision_id"]

    async def falla(self, *, revision_id, snapshot):
        raise RuntimeError("almacenamiento caído")

    monkeypatch.setattr(PostgresAuditoriaRepository, "registrar", falla)
    assert app.veredicto(revision_id).status_code == 500

    assert app.sql.escalar(
        "SELECT count(*) FROM sabre.veredicto v JOIN sabre.revision_var r ON r.id = v.revision_id "
        "JOIN sabre.tocado t ON t.id = r.tocado_id WHERE t.combate_id = :i", i=match_id,
    ) == 0
    assert app.sql.escalar(
        "SELECT count(*) FROM sabre.revision_var r JOIN sabre.tocado t ON t.id = r.tocado_id "
        "WHERE t.combate_id = :i AND r.cerrada_en IS NULL", i=match_id,
    ) == 1

    monkeypatch.undo()
    assert app.veredicto(revision_id).status_code == 200  # reintento posible
    _sin_filas_alteradas(app)


def test_pose_incompleta_registra_clasificacion_no_disponible(crear_app):
    app = crear_app(locked=False, extraccion_falla=True)
    match_id = app.configurar()

    resp = app.subir_clip(match_id)

    assert resp.status_code == 200
    assert resp.json()["motivo"] == "pose_incompleta"
    revision_id = resp.json()["revision_id"]
    clasif = app.sql.filas(
        "SELECT c.* FROM sabre.clasificacion c JOIN sabre.tocado t ON t.id = c.tocado_id "
        "WHERE t.combate_id = :i", i=match_id,
    )[0]
    assert clasif["disponible"] is False
    assert clasif["motivo_no_disp"] == "pose_incompleta"
    assert clasif["clase"] is None
    assert (app.storage_dir / clasif["keypoints_uri"].removeprefix("local://")).exists()
    # Sin sugerencia la regla es la misma: mantener/cambiar exigen clase_final...
    for decision in ("mantener", "cambiar"):
        assert app.veredicto(revision_id, decision=decision, clase_final=None).status_code == 422
    # ...y anular no la admite.
    assert app.veredicto(revision_id, decision="anular", clase_final="AtaqueA").status_code == 422
    assert app.sql.escalar(SQL_REVISIONES_ABIERTAS_DEL_COMBATE, i=match_id) == 1
    # El árbitro puede cerrar la revisión declarando su decisión final
    assert app.veredicto(revision_id, decision="cambiar", clase_final="AtaqueB").status_code == 200
    _sin_filas_alteradas(app)


class _NubeCaida(FakeVerdictSubscriber):
    async def wait_for_verdict(self, revision_id):
        await asyncio.Event().wait()


def test_timeout_de_cloud_registra_motivo_timeout(crear_app):
    app = crear_app(subscriber=_NubeCaida(VEREDICTO_DEFAULT), verdict_timeout_s=0.05)
    match_id = app.configurar()

    resp = app.subir_clip(match_id)

    assert resp.json()["timed_out"] is True
    assert app.sql.escalar(
        "SELECT c.motivo_no_disp FROM sabre.clasificacion c JOIN sabre.tocado t ON t.id = c.tocado_id "
        "WHERE t.combate_id = :i", i=match_id,
    ) == "timeout"


def test_no_disponible_de_cloud_registra_su_motivo(crear_app):
    resultado = UnavailableResult(
        match_id="x", revision_id="x", motivo=MotivoNoDisponible.MENSAJE_INVALIDO
    )

    class _Sub(FakeVerdictSubscriber):
        async def wait_for_verdict(self, revision_id):
            return resultado

    app = crear_app(subscriber=_Sub(VEREDICTO_DEFAULT))
    match_id = app.configurar()

    resp = app.subir_clip(match_id)

    assert resp.json()["disponible"] is False
    assert resp.json()["motivo"] == "mensaje_invalido"
    assert resp.json()["timed_out"] is False
    assert app.sql.escalar(
        "SELECT c.motivo_no_disp FROM sabre.clasificacion c JOIN sabre.tocado t ON t.id = c.tocado_id "
        "WHERE t.combate_id = :i", i=match_id,
    ) == "mensaje_invalido"


def test_clasificacion_es_unica_por_tocado_y_modelo(crear_app):
    """UNIQUE (tocado_id, modelo_version_id): registrar dos veces devuelve la
    misma fila en vez de fallar."""
    from fog.domain.models import TrackedSequence

    app = crear_app()
    match_id, _ = _combate_completo(app)
    tocado_id = app.sql.escalar("SELECT id FROM sabre.tocado WHERE combate_id = :i", i=match_id)
    revision_id = app.sql.escalar("SELECT id FROM sabre.revision_var WHERE tocado_id = :t", t=tocado_id)
    caso = app.container.registrar_clasificacion()
    tracked = TrackedSequence(frames=[], frame_w=64, frame_h=64, locked=True)
    otro = VerdictView(
        match_id=match_id, revision_id=str(revision_id), fencer="VER", action="RiposteB", confidence=0.5
    )

    nueva = asyncio.run(caso.execute(
        tocado_id=tocado_id, revision_id=revision_id, tracked=tracked, resultado=otro, latencia_ms=1,
    ))

    assert app.sql.escalar("SELECT count(*) FROM sabre.clasificacion WHERE tocado_id = :t", t=tocado_id) == 1
    assert nueva.clase == "AtaqueA"  # la original, sin sobrescribir


# ---------------------------------------------------------------------------
# Errores de entrada
# ---------------------------------------------------------------------------

def test_clip_sin_luz_encendida_responde_422_y_no_persiste(crear_app):
    app = crear_app()
    match_id = app.configurar()

    resp = app.subir_clip(match_id, has_luz_A="false", has_luz_B="false")

    assert resp.status_code == 422
    assert app.sql.escalar("SELECT count(*) FROM sabre.clip WHERE combate_id = :i", i=match_id) == 0


def test_clip_sin_instante_de_tocado_responde_422(crear_app):
    app = crear_app()
    match_id = app.configurar()

    assert app.subir_clip(match_id, t_tocado_ms=None).status_code == 422


def test_segundo_clip_del_mismo_combate_ya_no_responde_409(crear_app):
    app = crear_app()
    match_id, _ = _combate_completo(app)

    assert app.subir_clip(match_id).status_code == 200


class _SubscriberPorLlamada(FakeVerdictSubscriber):
    """Cloud doblado: un veredicto distinto por revisión, en orden de llegada."""

    def __init__(self, veredictos: list[VerdictView]):
        self._pendientes = list(veredictos)

    async def wait_for_verdict(self, revision_id):
        return self._pendientes.pop(0)


def test_dos_clips_del_mismo_combate_producen_dos_revisiones_independientes(crear_app):
    """Un combate admite N revisiones: cada clip abre la suya, con su propia
    clasificación y su propio veredicto."""
    def _veredicto(action: str, fencer: str, confianza: float) -> VerdictView:
        return VerdictView(
            match_id="x", revision_id="x", fencer=fencer, action=action, confidence=confianza,
            probs={action: confianza},
        )

    app = crear_app(subscriber=_SubscriberPorLlamada([
        _veredicto("AttackA", "ROJ", 0.8),
        _veredicto("RiposteB", "VER", 0.6),
    ]))
    match_id = app.configurar()
    clip_1 = app.subir_clip(match_id, has_luz_A="true", has_luz_B="false", t_tocado_ms="200")
    clip_2 = app.subir_clip(match_id, has_luz_A="false", has_luz_B="true", t_tocado_ms="400")
    assert clip_1.status_code == clip_2.status_code == 200
    rev_1, rev_2 = clip_1.json()["revision_id"], clip_2.json()["revision_id"]
    assert rev_1 != rev_2

    # Dos tocados, dos clips y dos revisiones del mismo combate
    for tabla in ("tocado", "clip"):
        assert app.sql.escalar(f"SELECT count(*) FROM sabre.{tabla} WHERE combate_id = :i", i=match_id) == 2
    assert app.sql.escalar(SQL_REVISIONES_ABIERTAS_DEL_COMBATE, i=match_id) == 2

    # Clasificaciones independientes (una por tocado)
    clasificaciones = {
        str(f["id"]): f for f in app.sql.filas(
            "SELECT r.id, c.clase, c.tirador, c.confianza, t.t_tocado_ms "
            "FROM sabre.revision_var r JOIN sabre.clasificacion c ON c.id = r.clasificacion_id "
            "JOIN sabre.tocado t ON t.id = r.tocado_id WHERE t.combate_id = :i", i=match_id,
        )
    }
    assert (clasificaciones[rev_1]["clase"], clasificaciones[rev_1]["t_tocado_ms"]) == ("AtaqueA", 200)
    assert (clasificaciones[rev_2]["clase"], clasificaciones[rev_2]["t_tocado_ms"]) == ("RiposteB", 400)

    # Veredictos independientes: cerrar una no toca la otra
    r2 = app.veredicto(rev_2, decision="cambiar", clase_final="AtaqueB")
    assert r2.status_code == 200, r2.text
    assert r2.json()["revision_id"] == rev_2
    assert app.sql.escalar(SQL_REVISIONES_ABIERTAS_DEL_COMBATE, i=match_id) == 1
    r1 = app.veredicto(rev_1, decision="mantener", clase_final="AtaqueA")
    assert r1.status_code == 200, r1.text
    assert r1.json()["revision_id"] == rev_1
    assert app.sql.escalar(SQL_REVISIONES_ABIERTAS_DEL_COMBATE, i=match_id) == 0
    assert app.sql.escalar(SQL_VEREDICTOS_DEL_COMBATE, i=match_id) == 2
    assert app.veredicto(rev_1, decision="anular").status_code == 409  # solo esa revisión
    filas = app.sql.filas(
        "SELECT r.id, v.decision, v.clase_final FROM sabre.veredicto v "
        "JOIN sabre.revision_var r ON r.id = v.revision_id "
        "JOIN sabre.tocado t ON t.id = r.tocado_id WHERE t.combate_id = :i", i=match_id,
    )
    assert {str(f["id"]): (f["decision"], f["clase_final"]) for f in filas} == {
        rev_1: ("mantener", "AtaqueA"), rev_2: ("cambiar", "AtaqueB"),
    }
    _sin_filas_alteradas(app)


def test_la_ruta_de_veredicto_por_combate_ya_no_existe(crear_app):
    app = crear_app()
    match_id, _ = _combate_completo(app)

    resp = app.client.post(
        f"/matches/{match_id}/veredicto",
        json={"decision": "mantener", "arbitro_id": str(app.arbitro_id)},
    )

    assert resp.status_code in (404, 405)
    assert app.sql.escalar(SQL_VEREDICTOS_DEL_COMBATE, i=match_id) == 0


def test_configurar_con_evento_o_arbitro_inexistente_responde_404(crear_app):
    app = crear_app()

    r1 = app.client.post("/matches/config", json=app.body_config(
        evento_id=str(uuid.uuid4()), alias_A="Fantasma"))
    r2 = app.client.post("/matches/config", json=app.body_config(
        arbitro_id=str(uuid.uuid4()), alias_A="Fantasma"))

    assert (r1.status_code, r2.status_code) == (404, 404)
    assert app.sql.escalar("SELECT count(*) FROM sabre.tirador WHERE alias = 'Fantasma'") == 0


def test_configurar_menor_con_consentimiento_sin_firmante_responde_422(crear_app):
    app = crear_app()

    resp = app.client.post("/matches/config", json=app.body_config(
        es_menor_A=True, consentimiento_firmado_A=True, consentimiento_fecha_A="2026-09-01",
    ))

    assert resp.status_code == 422


def test_configurar_sin_es_menor_responde_422(crear_app):
    app = crear_app()
    body = app.body_config()
    del body["es_menor_B"]

    assert app.client.post("/matches/config", json=body).status_code == 422


def test_veredicto_de_revision_inexistente_responde_404(crear_app):
    app = crear_app()

    assert app.veredicto(str(uuid.uuid4())).status_code == 404
    assert app.veredicto("no-es-un-uuid").status_code == 404


def test_vista_de_muestras_usa_clase_final_como_etiqueta_y_excluye_anular(crear_app):
    """v_muestras_confirmadas: la etiqueta es siempre `clase_final`, sin
    depender de si el árbitro mantuvo o cambió la acción sugerida."""
    app = crear_app()
    _, mantenida = _combate_completo(app)      # sugerida AtaqueA
    _, cambiada = _combate_completo(app)       # sugerida AtaqueA
    _, anulada = _combate_completo(app)
    assert app.veredicto(mantenida["revision_id"], decision="mantener", clase_final="RiposteB").status_code == 200
    assert app.veredicto(cambiada["revision_id"], decision="cambiar", clase_final="ContraataqueB").status_code == 200
    assert app.veredicto(anulada["revision_id"], decision="anular").status_code == 200

    ids = [uuid.UUID(c["revision_id"]) for c in (mantenida, cambiada, anulada)]
    filas = app.sql.filas(
        "SELECT revision_id, clase_sugerida, etiqueta, decision FROM sabre.v_muestras_confirmadas "
        "WHERE revision_id = ANY(:ids)", ids=ids,
    )

    assert {str(f["revision_id"]): (f["decision"], f["clase_sugerida"], f["etiqueta"]) for f in filas} == {
        mantenida["revision_id"]: ("mantener", "AtaqueA", "RiposteB"),
        cambiada["revision_id"]: ("cambiar", "AtaqueA", "ContraataqueB"),
    }
