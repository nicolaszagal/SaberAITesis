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

    async def wait_for_verdict(self, match_id: str) -> VerdictView:
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
        t_tocado_ms="1234",
        # Alias obsoleto, con un valor que produciría el resultado
        # contrario si el endpoint todavía lo usara como fuente principal.
        luz_frame_b="0",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_luz_A"] is True
    assert body["has_luz_B"] is False

    assert app.container.sessions().get(match_id).t_tocado_ms == 1234
    tocado = app.sql.filas("SELECT * FROM sabre.tocado WHERE combate_id = :i", i=match_id)[0]
    assert (tocado["luz_a"], tocado["luz_b"], tocado["t_tocado_ms"]) == (True, False, 1234)


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

    session = app.container.sessions().get(match_id)
    assert session is not None
    assert session.closed_at is not None
    assert session.unavailable is not None
    assert session.unavailable.motivo.value == "timeout"


def test_websocket_tardio_recibe_el_veredicto_del_combate_persistido(crear_app):
    app = crear_app(subscriber=FakeVerdictSubscriber(
        VerdictView(match_id="x", fencer="ROJ", action="AttackA", confidence=0.9)
    ))
    match_id = app.configurar()
    assert app.subir_clip(match_id).status_code == 200

    with app.client.websocket_connect(f"/ws/veredicto/{match_id}") as ws:
        mensaje = ws.receive_json()

    assert mensaje["type"] == "veredicto"
    assert mensaje["action"] == "AttackA"
