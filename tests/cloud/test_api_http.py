"""API HTTP de entrada de Cloud (DEPLOY11): autenticación por nodo, límites y contrato."""

from __future__ import annotations

import asyncio
import base64
import logging
import time

import httpx
import numpy as np
import pytest

from cloud.application.clasificar_secuencia import ClasificarSecuencia
from cloud.domain.models import ActionClass, RawVerdict
from cloud.infrastructure.api.app import crear_app
from cloud.infrastructure.api.nodos import (
    LimitadorPeticiones, NodosInvalidosError, RegistroNodos, hash_token,
)
from tests.cloud.fakes import FakeActionClassifier, IdentityArbitrationPolicy

TOKEN_ANA = "token-de-ana-" + "a" * 30
TOKEN_BETO = "token-de-beto-" + "b" * 30


def _registro() -> RegistroNodos:
    return RegistroNodos.desde_texto(f"ana:{hash_token(TOKEN_ANA)},beto:{hash_token(TOKEN_BETO)}")


def _crudo() -> RawVerdict:
    probs = {c.value: 0.02 for c in ActionClass}
    probs["ContrattackA"] = 0.9
    return RawVerdict(
        action_class=ActionClass.CONTRATTACK_A, confidence=0.9, probs=probs, atencion=[0.5, 0.25, 0.25],
    )


def _cuerpo(frames: int = 3, **cambios) -> dict:
    secuencia = np.zeros((frames, 192), dtype=np.float32)
    cuerpo = {
        "match_id": "m-1", "revision_id": "r-1", "shape": f"{frames},192", "dtype": "float32",
        "features": base64.b64encode(secuencia.tobytes()).decode(),
        "has_luz_A": True, "has_luz_B": False, "weapon_side_A": "right", "weapon_side_B": "left",
    }
    cuerpo.update(cambios)
    return cuerpo


def _app(clasificador=None, **kwargs):
    clasificador = clasificador or FakeActionClassifier(result=_crudo())
    caso = ClasificarSecuencia(clasificador, IdentityArbitrationPolicy(), "lstm_6class/run/best_model.pt")
    return crear_app(caso, _registro(), entorno="local", **kwargs), clasificador


def _cliente(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud")


def _auth(token=TOKEN_ANA) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_clasifica_y_devuelve_lo_mismo_que_el_veredicto_de_redis():
    app, clasificador = _app()
    async with _cliente(app) as c:
        r = await c.post("/v1/clasificar", json=_cuerpo(), headers=_auth())
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["disponible"] is True
    assert cuerpo["action_class"] == "ContrattackA"
    assert cuerpo["fencer"] == "ROJ"
    assert cuerpo["confidence"] == pytest.approx(0.9)
    assert cuerpo["modelo"] == "lstm_6class/run/best_model.pt"
    assert cuerpo["atencion"] == [0.5, 0.25, 0.25]
    assert cuerpo["revision_id"] == "r-1" and cuerpo["match_id"] == "m-1"
    assert cuerpo["latencia_inferencia_ms"] >= 0
    # La luz y la secuencia llegaron al clasificador tal como Fog las envió.
    secuencia, luz = clasificador.calls[0]
    assert secuencia.shape == (3, 192) and luz.has_luz_a and not luz.has_luz_b


@pytest.mark.parametrize("encabezados", [
    {},
    {"Authorization": "Bearer"},
    {"Authorization": "Basic " + TOKEN_ANA},
    {"Authorization": "Bearer token-inventado"},
    {"Authorization": "Bearer " + TOKEN_ANA + "x"},
])
async def test_sin_token_o_con_token_invalido_es_401(encabezados):
    app, clasificador = _app()
    async with _cliente(app) as c:
        r = await c.post("/v1/clasificar", json=_cuerpo(), headers=encabezados)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert clasificador.calls == []


async def test_token_revocado_es_401():
    """Revocar es quitar el hash del registro: el mismo token deja de valer."""
    caso = ClasificarSecuencia(FakeActionClassifier(result=_crudo()), IdentityArbitrationPolicy(), "m")
    sin_beto = RegistroNodos.desde_texto(f"ana:{hash_token(TOKEN_ANA)}")
    app = crear_app(caso, sin_beto, entorno="local")
    async with _cliente(app) as c:
        assert (await c.post("/v1/clasificar", json=_cuerpo(), headers=_auth(TOKEN_BETO))).status_code == 401
        assert (await c.post("/v1/clasificar", json=_cuerpo(), headers=_auth(TOKEN_ANA))).status_code == 200


async def test_cuerpo_declarado_demasiado_grande_es_413():
    app, clasificador = _app(max_body_bytes=1000)
    async with _cliente(app) as c:
        r = await c.post("/v1/clasificar", json=_cuerpo(frames=50), headers=_auth())
    assert r.status_code == 413
    assert clasificador.calls == []


async def test_cuerpo_grande_sin_content_length_es_413():
    app, clasificador = _app(max_body_bytes=1000)

    async def trozos():
        for _ in range(10):
            yield b"x" * 400

    async with _cliente(app) as c:
        r = await c.post("/v1/clasificar", content=trozos(), headers=_auth())
    assert r.status_code == 413
    assert clasificador.calls == []


async def test_limite_de_peticiones_por_token_es_429_y_no_afecta_a_otro_nodo():
    app, _ = _app(limitador=LimitadorPeticiones(maximo=2, ventana_s=60))
    async with _cliente(app) as c:
        estados = [(await c.post("/v1/clasificar", json=_cuerpo(), headers=_auth())).status_code for _ in range(3)]
        otro = await c.post("/v1/clasificar", json=_cuerpo(), headers=_auth(TOKEN_BETO))
    assert estados == [200, 200, 429]
    assert otro.status_code == 200


def test_limitador_libera_al_pasar_la_ventana():
    t = [0.0]
    limitador = LimitadorPeticiones(maximo=1, ventana_s=10, reloj=lambda: t[0])
    assert limitador.permitir("ana") is True
    assert limitador.permitir("ana") is False
    t[0] = 10.0
    assert limitador.permitir("ana") is True


@pytest.mark.parametrize("cambios", [
    {"shape": "3,100"},
    {"shape": "0,192"},
    {"shape": "abc"},
    {"dtype": "float64"},
    {"features": "no-es-base64!!"},
    {"features": base64.b64encode(b"corto").decode()},
    {"revision_id": ""},
])
async def test_cuerpo_que_no_respeta_el_contrato_es_422(cambios):
    app, clasificador = _app()
    async with _cliente(app) as c:
        r = await c.post("/v1/clasificar", json=_cuerpo(**cambios), headers=_auth())
    assert r.status_code == 422
    assert clasificador.calls == []


async def test_campo_faltante_o_extra_es_422_y_no_repite_lo_recibido():
    app, _ = _app()
    cuerpo = _cuerpo()
    del cuerpo["weapon_side_A"]
    cuerpo["intruso"] = "SECRETO-123"
    async with _cliente(app) as c:
        r = await c.post("/v1/clasificar", json=cuerpo, headers=_auth())
    assert r.status_code == 422
    assert "SECRETO-123" not in r.text


async def test_tiempo_maximo_por_peticion_es_504():
    class Lento(FakeActionClassifier):
        def classify(self, sequence, luz):
            time.sleep(0.3)
            return super().classify(sequence, luz)

    app, _ = _app(Lento(result=_crudo()), timeout_s=0.05)
    async with _cliente(app) as c:
        r = await c.post("/v1/clasificar", json=_cuerpo(), headers=_auth())
    assert r.status_code == 504


async def test_fallo_del_clasificador_es_500_generico():
    app, _ = _app(FakeActionClassifier(raises=RuntimeError("detalle interno")))
    async with _cliente(app) as c:
        r = await c.post("/v1/clasificar", json=_cuerpo(), headers=_auth())
    assert r.status_code == 500
    assert "detalle interno" not in r.text


async def test_health_no_exige_token_ni_expone_datos():
    app, _ = _app()
    async with _cliente(app) as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_en_remoto_no_hay_documentacion():
    caso = ClasificarSecuencia(FakeActionClassifier(result=_crudo()), IdentityArbitrationPolicy(), "m")
    app = crear_app(caso, _registro(), entorno="remoto")
    async with _cliente(app) as c:
        for ruta in ("/docs", "/redoc", "/openapi.json"):
            assert (await c.get(ruta)).status_code == 404


async def test_los_logs_llevan_el_nodo_y_el_tiempo_pero_nunca_token_ni_contenido(caplog):
    app, _ = _app()
    cuerpo = _cuerpo(revision_id="revision-visible-solo-en-cuerpo")
    with caplog.at_level(logging.DEBUG):
        async with _cliente(app) as c:
            await c.post("/v1/clasificar", json=cuerpo, headers=_auth())
            await c.post("/v1/clasificar", json=cuerpo, headers=_auth("token-inventado-xyz"))
    texto = "\n".join(r.getMessage() for r in caplog.records if r.name == "cloud.api")
    assert "[ana] POST /v1/clasificar -> 200 en " in texto and " ms" in texto
    for secreto in (TOKEN_ANA, "token-inventado-xyz", cuerpo["features"], cuerpo["match_id"]):
        assert secreto not in texto


async def test_cloud_no_persiste_las_features(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, _ = _app()
    async with _cliente(app) as c:
        await c.post("/v1/clasificar", json=_cuerpo(), headers=_auth())
    assert list(tmp_path.iterdir()) == []


# --- Registro de nodos ---------------------------------------------------------------------------

def test_registro_acepta_comas_y_saltos_de_linea_y_autentica():
    texto = f"ana:{hash_token('a')}\nbeto:{hash_token('b').upper()}, cruz-2:{hash_token('c')}"
    registro = RegistroNodos.desde_texto(texto)
    assert registro.nombres == ["ana", "beto", "cruz-2"]
    assert registro.autenticar("b") == "beto"
    assert registro.autenticar("nadie") is None


@pytest.mark.parametrize("texto", [
    "", "   ", None,
    "ana", "ana:", ":" + "a" * 64,
    "ana:" + "a" * 63, "ana:" + "g" * 64,
    "Ana:" + "a" * 64, "a" * 40 + ":" + "a" * 64,
    f"ana:{hash_token('a')},ana:{hash_token('b')}",
    f"ana:{hash_token('a')},beto:{hash_token('a')}",
])
def test_registro_rechaza_formatos_invalidos_sin_filtrar_hashes(texto):
    with pytest.raises(NodosInvalidosError) as e:
        RegistroNodos.desde_texto(texto)
    assert "a" * 64 not in str(e.value)


async def test_la_clasificacion_corre_en_un_solo_hilo_a_la_vez():
    """Dos peticiones simultáneas no entran juntas al modelo (el candado de hilo único)."""
    dentro, maximo = [0], [0]

    class Contador(FakeActionClassifier):
        def classify(self, sequence, luz):
            dentro[0] += 1
            maximo[0] = max(maximo[0], dentro[0])
            time.sleep(0.05)
            dentro[0] -= 1
            return super().classify(sequence, luz)

    app, _ = _app(Contador(result=_crudo()))
    async with _cliente(app) as c:
        await asyncio.gather(*[c.post("/v1/clasificar", json=_cuerpo(), headers=_auth(TOKEN_BETO)) for _ in range(3)])
    assert maximo[0] == 1
