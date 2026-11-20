"""Transporte HTTP de Fog hacia Cloud (DEPLOY11): publica features y entrega el veredicto."""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import httpx
import numpy as np
import pytest

from fog import composition
from fog.application.forward_verdict import ForwardVerdictToClient
from fog.domain.models import (
    ExtractedFeatures, LuzSignal, MotivoNoDisponible, UnavailableResult, VerdictView, WeaponSide,
)
from fog.infrastructure.messaging.cloud_sonda_salud import CloudSonda
from fog.infrastructure.messaging.http_cloud_transport import HttpCloudTransport
from fog.infrastructure.sesiones.session_registry import SessionRegistry
from shared import config
from tests.fog.fakes import FakeModelos

TOKEN = "token-secreto-del-nodo-" + "x" * 20
MODELO = "lstm_6class/run/best_model.pt"


def _respuesta_ok(revision_id="r1", **extra) -> dict:
    cuerpo = {
        "match_id": "m1", "revision_id": revision_id, "disponible": True,
        "action_class": "ContrattackA", "confidence": 0.9, "fencer": "ROJ",
        "probs": {"ContrattackA": 0.9}, "latencia_inferencia_ms": 12, "modelo": MODELO,
        "atencion": [0.5, 0.5],
    }
    cuerpo.update(extra)
    return cuerpo


def _transporte(manejador, **kwargs) -> tuple[HttpCloudTransport, list[httpx.Request]]:
    vistas: list[httpx.Request] = []

    def envoltorio(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return manejador(request)

    cliente = httpx.AsyncClient(
        transport=httpx.MockTransport(envoltorio), base_url="https://cloud.ejemplo.test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    return HttpCloudTransport("https://cloud.ejemplo.test", TOKEN, 5.0, cliente=cliente, **kwargs), vistas


def _features(frames=4) -> ExtractedFeatures:
    return ExtractedFeatures(sequence=np.arange(frames * 192, dtype=np.float32).reshape(frames, 192))


async def _pedir(transporte, revision_id="r1", aceptar=None):
    await transporte.publish(
        "m1", revision_id, _features(), LuzSignal(has_luz_a=True, has_luz_b=False),
        WeaponSide.RIGHT, WeaponSide.LEFT,
    )
    return await transporte.wait_for_verdict(revision_id, aceptar)


async def test_publica_el_contrato_y_entrega_el_veredicto_de_cloud():
    transporte, vistas = _transporte(lambda r: httpx.Response(200, json=_respuesta_ok()))
    resultado = await _pedir(transporte)

    assert resultado == VerdictView(
        match_id="m1", revision_id="r1", fencer="ROJ", action="ContrattackA", confidence=0.9,
        probs={"ContrattackA": 0.9}, latencia_inferencia_ms=12, modelo=MODELO, atencion=[0.5, 0.5],
    )
    peticion = vistas[0]
    assert (peticion.method, peticion.url.path) == ("POST", "/v1/clasificar")
    assert peticion.headers["authorization"] == f"Bearer {TOKEN}"
    cuerpo = json.loads(peticion.content)
    assert cuerpo["shape"] == "4,192" and cuerpo["dtype"] == "float32"
    assert cuerpo["has_luz_A"] is True and cuerpo["has_luz_B"] is False
    assert (cuerpo["weapon_side_A"], cuerpo["weapon_side_B"]) == ("right", "left")
    recibido = np.frombuffer(base64.b64decode(cuerpo["features"]), dtype=np.float32).reshape(4, 192)
    np.testing.assert_array_equal(recibido, _features().sequence)


async def test_cloud_no_disponible_se_entrega_con_su_motivo():
    cuerpo = {"revision_id": "r1", "disponible": False, "motivo_no_disp": "confianza_baja"}
    transporte, _ = _transporte(lambda r: httpx.Response(200, json=cuerpo))
    resultado = await _pedir(transporte)
    assert resultado == UnavailableResult(match_id="m1", revision_id="r1", motivo=MotivoNoDisponible.CONFIANZA_BAJA)


@pytest.mark.parametrize("estado, motivo", [
    (400, MotivoNoDisponible.MENSAJE_INVALIDO),
    (413, MotivoNoDisponible.MENSAJE_INVALIDO),
    (422, MotivoNoDisponible.MENSAJE_INVALIDO),
    (401, MotivoNoDisponible.TIMEOUT),   # token inválido o revocado
    (429, MotivoNoDisponible.TIMEOUT),   # límite de peticiones
    (500, MotivoNoDisponible.TIMEOUT),
    (504, MotivoNoDisponible.TIMEOUT),
])
async def test_si_cloud_rechaza_o_falla_la_revision_queda_no_disponible(estado, motivo):
    transporte, _ = _transporte(lambda r: httpx.Response(estado, json={"detail": "x"}))
    resultado = await _pedir(transporte)
    assert resultado == UnavailableResult(match_id="m1", revision_id="r1", motivo=motivo)


@pytest.mark.parametrize("fallo", [
    httpx.ReadTimeout("lento"), httpx.ConnectTimeout("lento"), httpx.ConnectError("sin red"),
])
async def test_si_cloud_no_responde_a_tiempo_es_timeout(fallo):
    def manejador(request):
        raise fallo

    transporte, _ = _transporte(manejador)
    resultado = await _pedir(transporte)
    assert resultado.motivo == MotivoNoDisponible.TIMEOUT


@pytest.mark.parametrize("respuesta", [
    httpx.Response(200, text="no es json"),
    httpx.Response(200, json={"revision_id": "r1", "disponible": True}),            # faltan campos
    httpx.Response(200, json=_respuesta_ok(revision_id="otra-revision")),            # de otra revisión
    httpx.Response(200, json={"revision_id": "r1", "disponible": False, "motivo_no_disp": "inventado"}),
])
async def test_respuesta_ilegible_o_ajena_es_timeout(respuesta):
    transporte, _ = _transporte(lambda r: respuesta)
    resultado = await _pedir(transporte)
    assert isinstance(resultado, UnavailableResult) and resultado.motivo == MotivoNoDisponible.TIMEOUT


async def test_resultado_no_aceptado_no_se_entrega_como_veredicto():
    transporte, _ = _transporte(lambda r: httpx.Response(200, json=_respuesta_ok()))

    async def rechazar(resultado):
        return False

    resultado = await _pedir(transporte, aceptar=rechazar)
    assert isinstance(resultado, UnavailableResult) and resultado.motivo == MotivoNoDisponible.TIMEOUT


async def test_cada_revision_recibe_su_propio_resultado():
    def manejador(request):
        rev = json.loads(request.content)["revision_id"]
        return httpx.Response(200, json=_respuesta_ok(revision_id=rev, action_class="RiposteB" if rev == "r2" else "AttackA"))

    transporte, _ = _transporte(manejador)
    for rev in ("r1", "r2"):
        await transporte.publish("m1", rev, _features(), LuzSignal.none(), WeaponSide.RIGHT, WeaponSide.RIGHT)
    r2 = await transporte.wait_for_verdict("r2")
    r1 = await transporte.wait_for_verdict("r1")
    assert (r1.action, r2.action) == ("AttackA", "RiposteB")


async def test_si_quien_espera_se_cancela_la_peticion_se_cancela_y_no_queda_pendiente():
    cancelada = asyncio.Event()

    async def lento(request):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelada.set()
            raise

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(lento), base_url="https://cloud.ejemplo.test")
    transporte = HttpCloudTransport("https://cloud.ejemplo.test", TOKEN, 5.0, cliente=cliente)
    await transporte.publish("m1", "r1", _features(), LuzSignal.none(), WeaponSide.RIGHT, WeaponSide.RIGHT)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(transporte.wait_for_verdict("r1"), timeout=0.05)
    await asyncio.wait_for(cancelada.wait(), timeout=1)
    assert transporte._pendientes == {}


async def test_el_token_no_aparece_en_ningun_log(caplog):
    def manejador(request):
        raise httpx.ConnectError(f"fallo hacia {request.url} con {request.headers['authorization']}")

    transporte, _ = _transporte(manejador)
    with caplog.at_level(logging.DEBUG):
        await _pedir(transporte)
        transporte2, _ = _transporte(lambda r: httpx.Response(401, json={}))
        await _pedir(transporte2)
    assert TOKEN not in caplog.text
    propios = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("fog"))
    assert "cloud.ejemplo.test" not in propios  # ni la dirección: el mensaje de httpx puede incluirla


async def test_sin_secuencia_no_se_publica():
    transporte, vistas = _transporte(lambda r: httpx.Response(200, json=_respuesta_ok()))
    with pytest.raises(ValueError):
        await transporte.publish("m1", "r1", ExtractedFeatures(sequence=None), LuzSignal.none(),
                                 WeaponSide.RIGHT, WeaponSide.RIGHT)
    assert vistas == []


async def test_con_el_caso_de_uso_de_veredicto_la_sesion_recibe_el_resultado():
    """El dominio no cambia: ForwardVerdictToClient funciona igual con el transporte HTTP."""
    transporte, _ = _transporte(lambda r: httpx.Response(200, json=_respuesta_ok()))
    sesiones = SessionRegistry()
    sesion = sesiones.create("m1", "r1", WeaponSide.RIGHT, WeaponSide.LEFT)
    await transporte.publish("m1", "r1", _features(), LuzSignal.none(), WeaponSide.RIGHT, WeaponSide.LEFT)

    await ForwardVerdictToClient(transporte, sesiones, FakeModelos()).execute("r1")

    assert sesion.verdict is not None and sesion.verdict.action == "ContrattackA"
    assert sesion.closed_at is not None


async def test_con_modelo_distinto_del_activo_el_veredicto_se_descarta():
    transporte, _ = _transporte(lambda r: httpx.Response(200, json=_respuesta_ok(modelo="lstm_6class/otro/best_model.pt")))
    sesiones = SessionRegistry()
    sesion = sesiones.create("m1", "r1", WeaponSide.RIGHT, WeaponSide.LEFT)
    await transporte.publish("m1", "r1", _features(), LuzSignal.none(), WeaponSide.RIGHT, WeaponSide.LEFT)

    await ForwardVerdictToClient(transporte, sesiones, FakeModelos()).execute("r1")

    assert sesion.verdict is None
    assert sesion.unavailable.motivo == MotivoNoDisponible.TIMEOUT


# --- URL admitida ---------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://cloud.ejemplo.test", "https://cloud.ejemplo.test/", "http://localhost:8002", "http://127.0.0.1:8002",
])
def test_urls_admitidas(url):
    assert config.validar_cloud_url(url) == url.rstrip("/")


@pytest.mark.parametrize("url", [
    "", "http://cloud.ejemplo.test", "http://192.168.1.10:8002", "http://localhost.evil.test",
    "ftp://cloud.ejemplo.test", "cloud.ejemplo.test", "https://", "https://usuario:S3creta9@cloud.ejemplo.test",
])
def test_urls_rechazadas_sin_filtrar_credenciales(url):
    with pytest.raises(RuntimeError) as e:
        config.validar_cloud_url(url)
    assert "S3creta9" not in str(e.value) and "usuario:" not in str(e.value)


def test_el_transporte_rechaza_http_hacia_un_host_remoto():
    with pytest.raises(RuntimeError):
        HttpCloudTransport("http://cloud.ejemplo.test", TOKEN, 5.0)


def test_token_se_lee_del_archivo_y_se_limpia(tmp_path):
    archivo = tmp_path / "cloud_token.txt"
    archivo.write_text(f"  {TOKEN}\n")
    assert config.leer_token_cloud(str(archivo)) == TOKEN


def test_token_ausente_o_vacio_falla_sin_mostrar_contenido(tmp_path):
    with pytest.raises(RuntimeError, match="importar-token"):
        config.leer_token_cloud(str(tmp_path / "no-existe.txt"))
    vacio = tmp_path / "vacio.txt"
    vacio.write_text("\n")
    with pytest.raises(RuntimeError, match="vacío"):
        config.leer_token_cloud(str(vacio))


def test_transporte_desconocido_se_rechaza():
    with pytest.raises(RuntimeError):
        config.validar_transporte_cloud("ftp")


# --- Sonda de salud -------------------------------------------------------------------------------

async def _sonda(manejador) -> CloudSonda:
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(manejador))
    return CloudSonda("https://cloud.ejemplo.test", cliente=cliente)


async def test_la_sonda_consulta_health_de_cloud():
    vistas = []

    def manejador(request):
        vistas.append(request)
        return httpx.Response(200, json={"status": "ok"})

    assert await (await _sonda(manejador)).responde() is True
    assert vistas[0].url.path == "/health"
    assert "authorization" not in vistas[0].headers


@pytest.mark.parametrize("respuesta", [
    httpx.Response(503, json={"status": "ok"}),
    httpx.Response(200, json={"status": "caido"}),
    httpx.Response(200, text="html"),
])
async def test_la_sonda_es_false_si_cloud_no_esta_sano(respuesta):
    assert await (await _sonda(lambda r: respuesta)).responde() is False


async def test_la_sonda_es_false_si_no_hay_red():
    def manejador(request):
        raise httpx.ConnectError("sin red")

    assert await (await _sonda(manejador)).responde() is False


# --- Composición: con `http` no se abre Redis ----------------------------------------------------

def test_con_http_fog_no_abre_conexiones_a_redis(monkeypatch, tmp_path):
    def prohibido(*a, **k):
        raise AssertionError("Fog abrió una conexión a Redis con CLOUD_TRANSPORTE=http")

    monkeypatch.setattr(composition.redis, "from_url", prohibido)
    token = tmp_path / "cloud_token.txt"
    token.write_text(TOKEN)

    contenedor = composition.Container()
    contenedor.config.cloud_transporte.from_value("http")
    contenedor.config.cloud_url.from_value("https://cloud.ejemplo.test")
    contenedor.config.cloud_token_file.from_value(str(token))
    contenedor.config.cloud_http_timeout_s.from_value(5.0)
    contenedor.config.redis_url.from_value("redis://no-debe-usarse:6379/0")

    publicador, suscriptor = contenedor.feature_publisher(), contenedor.verdict_subscriber()
    assert isinstance(publicador, HttpCloudTransport) and publicador is suscriptor
    assert isinstance(contenedor.sonda_nube(), CloudSonda)


def test_con_redis_el_publicador_sigue_siendo_el_de_redis(monkeypatch):
    from fog.infrastructure.messaging.redis_feature_publisher import RedisFeaturePublisher
    from fog.infrastructure.messaging.redis_verdict_subscriber import RedisVerdictSubscriber

    contenedor = composition.Container()
    contenedor.config.redis_url.from_value("redis://localhost:6379/0")
    assert isinstance(contenedor.feature_publisher(), RedisFeaturePublisher)
    assert isinstance(contenedor.verdict_subscriber(), RedisVerdictSubscriber)
