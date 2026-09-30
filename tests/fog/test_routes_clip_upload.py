"""Pruebas de integración (TestClient) de POST /matches/{match_id}/clip y
POST /matches/config, ahora sobre el combate persistido (D03; PostgreSQL
real vía `crear_app`, ver conftest.py):

- DEF-08: un clip sin tiradores debe responder de inmediato con
  disponible=false y motivo=pose_incompleta, en vez de esperar los 30 s
  del timeout de Cloud.
- DEF-13: weapon_side_A/B inválido -> 422 (TC-NEG-01); archivo que no abre
  como video, clip por debajo de MIN_FRAMES o por encima de CLIP_MAX_MB ->
  400/413 en vez de 500 (TC-NEG-02 y afines).
- DEF-14: has_luz_A/has_luz_B (bool) reemplazan a luz_frame_a/b como forma
  primaria de reportar la luz Favero en la carga de clip; luz_frame_a/b
  quedan como alias obsoleto, y t_tocado_ms se guarda en la sesión (y en
  `tocado`, D03) sin usarse para recortar.
- DEF-16: el timeout de Cloud cierra la sesión.

Dobla el estimador de pose (no corre YOLO real) y todo lo que toca Redis
(publisher/subscriber), igual que tests/fog/fakes.py.
"""

from __future__ import annotations

import asyncio
import time

from fog.domain.models import VerdictView
from fog.ports.verdict_subscriber import VerdictStreamSubscriberPort
from tests.fog.conftest import clip_de_prueba
from tests.fog.fakes import FakeVerdictSubscriber


class _HangingVerdictSubscriber(VerdictStreamSubscriberPort):
    """Nunca resuelve: simula que Cloud no responde, para ejercitar la
    rama de timeout de POST /matches/{match_id}/clip (DEF-16)."""

    async def wait_for_verdict(self, revision_id: str) -> VerdictView:
        await asyncio.Event().wait()


def test_clip_without_fencers_responds_fast_as_unavailable(crear_app):
    app = crear_app(locked=False, extraccion_falla=True)
    match_id = app.configurar()

    start = time.monotonic()
    response = app.subir_clip(match_id)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"tardó {elapsed:.2f}s, se esperaba respuesta inmediata (sin esperar a Cloud)"
    assert response.status_code == 200

    body = response.json()
    assert body["disponible"] is False
    assert body["motivo"] == "pose_incompleta"
    assert body["timed_out"] is False
    assert body["fencer"] is None
    assert body["action"] is None
    assert body["confidence"] is None
    assert app.container.feature_publisher().published == []


def test_upload_clip_below_min_frames_returns_400(crear_app):
    """DEF-13: un video real pero por debajo de MIN_FRAMES (fixture usa 3)
    se rechaza con 400 antes de correr pose/tracking."""
    app = crear_app()
    match_id = app.configurar()

    response = app.subir_clip(match_id, clip=clip_de_prueba(n_frames=1))

    assert response.status_code == 400
    assert "detail" in response.json()
    assert app.container.feature_publisher().published == []
    assert app.sql.escalar("SELECT count(*) FROM sabre.clip WHERE combate_id = :i", i=match_id) == 0


def test_upload_clip_over_max_size_returns_413(crear_app):
    """DEF-13: un clip por encima de CLIP_MAX_MB responde 413 sin llegar a
    correr pose/tracking."""
    app = crear_app(clip_max_mb=1e-6)  # ~1 byte, cualquier clip real lo supera
    match_id = app.configurar()

    response = app.subir_clip(match_id)

    assert response.status_code == 413
    assert "detail" in response.json()
    assert app.container.feature_publisher().published == []


def test_upload_clip_has_luz_fields_take_precedence_over_legacy_alias(crear_app):
    """DEF-14: has_luz_A/has_luz_B (bool) son la forma vigente; si vienen,
    ganan sobre luz_frame_a/b aunque el alias obsoleto también se envíe.
    También verifica que t_tocado_ms quede guardado en la sesión y en
    `tocado` sin afectar la respuesta (no se usa para recortar)."""
    app = crear_app()
    match_id = app.configurar()

    response = app.subir_clip(
        match_id,
        has_luz_A="true",
        has_luz_B="false",
        t_tocado_ms="400",
        # Alias obsoleto, con un valor que produciría el resultado
        # contrario si el endpoint todavía lo usara como fuente principal.
        luz_frame_b="0",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_luz_A"] is True
    assert body["has_luz_B"] is False

    assert app.container.sessions().get(body["revision_id"]).t_tocado_ms == 400
    tocado = app.sql.filas("SELECT * FROM sabre.tocado WHERE combate_id = :i", i=match_id)[0]
    assert (tocado["luz_a"], tocado["luz_b"], tocado["t_tocado_ms"]) == (True, False, 400)


def test_upload_clip_legacy_alias_used_when_new_fields_absent(crear_app):
    """DEF-14: sin has_luz_A/has_luz_B, luz_frame_a/b sigue funcionando
    como alias obsoleto para no romper clientes viejos."""
    app = crear_app()
    match_id = app.configurar()

    response = app.subir_clip(match_id, has_luz_A=None, has_luz_B=None, luz_frame_a="0")

    assert response.status_code == 200
    body = response.json()
    assert body["has_luz_A"] is True
    assert body["has_luz_B"] is False


def test_weapon_side_invalid_value_returns_422(crear_app):
    """TC-NEG-01 (DEF-13): weapon_side_A/B tipan Literal["right", "left"]
    en los esquemas, así que un valor fuera de ese enum ("zurdo") lo
    rechaza la validación de Pydantic antes de tocar el dominio."""
    app = crear_app()

    response = app.client.post("/matches/config", json=app.body_config(weapon_side_A="zurdo"))

    assert response.status_code == 422


def test_upload_clip_non_video_file_returns_400(crear_app):
    """TC-NEG-02 (DEF-13): un archivo que cv2 no puede abrir como video
    (texto plano con extensión .mp4) responde 400 con detail, en vez de un
    500 (DEF-13) o de esperar a Cloud."""
    app = crear_app()
    match_id = app.configurar()

    response = app.subir_clip(match_id, clip=b"esto no es un video")

    assert response.status_code == 400
    assert "detail" in response.json()
    assert app.container.feature_publisher().published == []


def test_upload_clip_marks_session_closed_when_cloud_times_out(crear_app):
    """DEF-16: el timeout de Cloud es, para el front, otro caso de "no
    disponible" — la sesión debe quedar cerrada (closed_at) para que
    SessionRegistry.sweep_expired la libere pasado SESSION_TTL_S, en vez
    de acumularse para siempre."""
    app = crear_app(subscriber=_HangingVerdictSubscriber(), verdict_timeout_s=0.05)
    match_id = app.configurar()

    response = app.subir_clip(match_id)

    assert response.status_code == 200
    body = response.json()
    assert body["timed_out"] is True
    assert body["disponible"] is False
    assert body["motivo"] == "timeout"

    session = app.container.sessions().get(body["revision_id"])
    assert session is not None
    assert session.closed_at is not None
    assert session.unavailable is not None
    assert session.unavailable.motivo.value == "timeout"


def test_websocket_tardio_recibe_el_veredicto_de_la_revision(crear_app):
    app = crear_app(subscriber=FakeVerdictSubscriber(
        VerdictView(match_id="x", revision_id="x", fencer="ROJ", action="AttackA", confidence=0.9)
    ))
    match_id = app.configurar()
    resp = app.subir_clip(match_id)
    assert resp.status_code == 200
    revision_id = resp.json()["revision_id"]

    with app.client.websocket_connect(f"/ws/veredicto/{revision_id}") as ws:
        mensaje = ws.receive_json()

    assert mensaje["type"] == "veredicto"
    assert mensaje["action"] == "AttackA"
    assert mensaje["revision_id"] == revision_id


class _SubscriberPorRevision(VerdictStreamSubscriberPort):
    """Cloud doblado: responde según el `revision_id` que recibe."""

    def __init__(self, veredictos: list[dict]):
        self._pendientes = list(veredictos)

    async def wait_for_verdict(self, revision_id: str) -> VerdictView:
        return VerdictView(match_id="m", revision_id=revision_id, **self._pendientes.pop(0))


def test_dos_clips_del_mismo_combate_tienen_websocket_y_veredicto_independientes(crear_app):
    app = crear_app(subscriber=_SubscriberPorRevision([
        dict(fencer="ROJ", action="AttackA", confidence=0.9),
        dict(fencer="VER", action="RiposteB", confidence=0.6),
    ]))
    match_id = app.configurar()

    primero = app.subir_clip(match_id)
    segundo = app.subir_clip(match_id)

    assert primero.status_code == segundo.status_code == 200
    rev_1, rev_2 = primero.json()["revision_id"], segundo.json()["revision_id"]
    assert rev_1 != rev_2
    assert (primero.json()["action"], segundo.json()["action"]) == ("AttackA", "RiposteB")
    with app.client.websocket_connect(f"/ws/veredicto/{rev_2}") as ws:
        mensaje_2 = ws.receive_json()
    with app.client.websocket_connect(f"/ws/veredicto/{rev_1}") as ws:
        mensaje_1 = ws.receive_json()
    assert (mensaje_1["revision_id"], mensaje_1["action"]) == (rev_1, "AttackA")
    assert (mensaje_2["revision_id"], mensaje_2["action"]) == (rev_2, "RiposteB")


def test_publica_en_redis_con_el_revision_id_de_cada_clip(crear_app):
    app = crear_app()
    match_id = app.configurar()

    primero = app.subir_clip(match_id).json()
    segundo = app.subir_clip(match_id).json()

    publicados = app.container.feature_publisher().published
    assert [(p[0], p[1]) for p in publicados] == [
        (match_id, primero["revision_id"]),
        (match_id, segundo["revision_id"]),
    ]


def _sin_rastro_del_clip(app, match_id: str) -> None:
    assert app.sql.escalar("SELECT count(*) FROM sabre.clip WHERE combate_id = :i", i=match_id) == 0
    assert app.sql.escalar("SELECT count(*) FROM sabre.tocado WHERE combate_id = :i", i=match_id) == 0
    assert app.container.feature_publisher().published == []
    assert not list(app.storage_dir.rglob("*.mp4"))


def test_t_tocado_ms_mayor_que_la_duracion_del_clip_responde_422(crear_app):
    # clip_de_prueba: 5 frames a 10 fps = 500 ms
    app = crear_app()
    match_id = app.configurar()

    response = app.subir_clip(match_id, t_tocado_ms="501")

    assert response.status_code == 422
    assert "501" in response.json()["detail"] and "500" in response.json()["detail"]
    _sin_rastro_del_clip(app, match_id)


def test_t_tocado_ms_negativo_responde_422(crear_app):
    app = crear_app()
    match_id = app.configurar()

    assert app.subir_clip(match_id, t_tocado_ms="-1").status_code == 422
    _sin_rastro_del_clip(app, match_id)


def test_t_tocado_ms_en_los_extremos_del_clip_se_acepta(crear_app):
    app = crear_app()
    match_id = app.configurar()

    inicio = app.subir_clip(match_id, t_tocado_ms="0")
    final = app.subir_clip(match_id, t_tocado_ms="500")

    assert inicio.status_code == final.status_code == 200
    guardados = app.sql.filas(
        "SELECT t_tocado_ms FROM sabre.tocado WHERE combate_id = :i ORDER BY t_tocado_ms", i=match_id
    )
    assert [g["t_tocado_ms"] for g in guardados] == [0, 500]


# ---------------------------------------------------------------------------
# V02: instante de cada luz Favero simulada
# ---------------------------------------------------------------------------


def _sin_legacy(**campos):
    """Campos de carga con solo la forma vigente (sin has_luz ni t_tocado_ms)."""
    return {"has_luz_A": None, "has_luz_B": None, "t_tocado_ms": None, **campos}


def _tocado(app, match_id):
    return app.sql.filas("SELECT * FROM sabre.tocado WHERE combate_id = :i", i=match_id)[0]


def test_dos_luces_guardan_cada_instante_y_t_tocado_es_el_menor(crear_app):
    app = crear_app()
    match_id = app.configurar()

    response = app.subir_clip(match_id, **_sin_legacy(t_luz_a_ms="400", t_luz_b_ms="200"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["has_luz_A"], body["has_luz_B"]) == (True, True)
    tocado = _tocado(app, match_id)
    assert (tocado["luz_a"], tocado["luz_b"]) == (True, True)
    assert (tocado["t_luz_a_ms"], tocado["t_luz_b_ms"], tocado["t_tocado_ms"]) == (400, 200, 200)
    assert app.container.sessions().get(body["revision_id"]).t_tocado_ms == 200
    frame = app.sql.filas(
        "SELECT frame_tocado FROM sabre.tocado_clip WHERE tocado_id = :t", t=tocado["id"]
    )[0]["frame_tocado"]
    assert frame == round(0.2 * 10)  # clip de prueba a 10 fps


def test_una_luz_deja_la_otra_apagada_sin_instante(crear_app):
    app = crear_app()
    match_id = app.configurar()

    response = app.subir_clip(match_id, **_sin_legacy(t_luz_b_ms="300"))

    assert response.status_code == 200, response.text
    tocado = _tocado(app, match_id)
    assert (tocado["luz_a"], tocado["luz_b"]) == (False, True)
    assert (tocado["t_luz_a_ms"], tocado["t_luz_b_ms"], tocado["t_tocado_ms"]) == (None, 300, 300)


def test_sin_ningun_instante_de_luz_responde_422_y_no_persiste(crear_app):
    app = crear_app()
    match_id = app.configurar()

    assert app.subir_clip(match_id, **_sin_legacy()).status_code == 422
    _sin_rastro_del_clip(app, match_id)


def test_instante_de_luz_fuera_del_clip_o_negativo_responde_422(crear_app):
    # clip_de_prueba: 5 frames a 10 fps = 500 ms
    app = crear_app()
    match_id = app.configurar()

    fuera = app.subir_clip(match_id, **_sin_legacy(t_luz_a_ms="300", t_luz_b_ms="501"))
    negativo = app.subir_clip(match_id, **_sin_legacy(t_luz_a_ms="-1"))

    assert fuera.status_code == negativo.status_code == 422
    assert "t_luz_b_ms=501" in fuera.json()["detail"]
    _sin_rastro_del_clip(app, match_id)


def test_instantes_de_luz_en_los_extremos_del_clip_se_aceptan(crear_app):
    app = crear_app()
    match_id = app.configurar()

    assert app.subir_clip(match_id, **_sin_legacy(t_luz_a_ms="0", t_luz_b_ms="500")).status_code == 200


def test_alias_obsoleto_has_luz_y_t_tocado_ms_completa_el_instante_de_cada_luz(crear_app):
    app = crear_app()
    match_id = app.configurar()

    response = app.subir_clip(match_id, has_luz_A="true", has_luz_B="true", t_tocado_ms="300")

    assert response.status_code == 200
    tocado = _tocado(app, match_id)
    assert (tocado["t_luz_a_ms"], tocado["t_luz_b_ms"], tocado["t_tocado_ms"]) == (300, 300, 300)


def test_alias_obsoleto_sin_instante_responde_422(crear_app):
    app = crear_app()
    match_id = app.configurar()

    assert app.subir_clip(match_id, t_tocado_ms=None).status_code == 422
    _sin_rastro_del_clip(app, match_id)


def test_misma_luz_y_misma_sugerencia_con_los_instantes_que_con_el_alias_obsoleto(crear_app):
    """V02 no toca la entrada del modelo: lo que llega a Redis (luz A/B) y la
    sugerencia son idénticas con la forma vigente y con el alias obsoleto."""
    app = crear_app()
    match_id = app.configurar()

    nuevo = app.subir_clip(match_id, **_sin_legacy(t_luz_a_ms="400", t_luz_b_ms="200")).json()
    viejo = app.subir_clip(match_id, has_luz_A="true", has_luz_B="true", t_tocado_ms="200").json()

    publicados = app.container.feature_publisher().published
    assert publicados[-2][3] == publicados[-1][3]  # LuzSignal idéntico
    assert publicados[-2][2].sequence.shape == publicados[-1][2].sequence.shape
    for campo in ("action", "fencer", "confidence", "disponible", "motivo"):
        assert nuevo[campo] == viejo[campo]
