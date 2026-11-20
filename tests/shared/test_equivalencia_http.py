"""La prueba de equivalencia del modo remoto clasifica a través de Cloud por HTTP (DEPLOY11)."""

import importlib.util
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest

from cloud.application.clasificar_secuencia import ClasificarSecuencia
from cloud.domain.models import ActionClass, LuzSignal, RawVerdict
from cloud.infrastructure.api.app import crear_app
from cloud.infrastructure.api.nodos import RegistroNodos, hash_token
from shared import config
from tests.cloud.fakes import FakeActionClassifier, IdentityArbitrationPolicy

BACKEND = Path(__file__).resolve().parents[2]
TOKEN = "token-de-prueba-" + "z" * 30


@pytest.fixture
def equivalencia(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND / "scripts"))
    spec = importlib.util.spec_from_file_location("equivalencia_http", BACKEND / "scripts" / "equivalencia.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["equivalencia_http"] = modulo
    spec.loader.exec_module(modulo)
    yield modulo
    sys.modules.pop("equivalencia_http", None)


def test_el_clasificador_http_devuelve_clase_y_probabilidades_de_cloud(equivalencia, monkeypatch, tmp_path):
    token = tmp_path / "cloud_token.txt"
    token.write_text(TOKEN + "\n")
    monkeypatch.setattr(config, "CLOUD_URL", "https://cloud.ejemplo.test")
    monkeypatch.setattr(config, "CLOUD_TOKEN_FILE", str(token))

    probs = {c.value: 0.02 for c in ActionClass}
    probs["RiposteB"] = 0.9
    crudo = RawVerdict(action_class=ActionClass.RIPOSTE_B, confidence=0.9, probs=probs, atencion=[1.0])
    caso = ClasificarSecuencia(FakeActionClassifier(result=crudo), IdentityArbitrationPolicy(), "lstm_6class/r/best_model.pt")
    app = crear_app(caso, RegistroNodos.desde_texto(f"prueba:{hash_token(TOKEN)}"), entorno="local")

    clasificador = equivalencia.ClasificadorCloudHttp()
    clasificador._transporte._cliente = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://cloud.ejemplo.test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    veredicto = clasificador.classify(np.zeros((5, 192), dtype=np.float32), LuzSignal(False, True))

    assert veredicto.action_class.value == "RiposteB"
    assert veredicto.probs["RiposteB"] == pytest.approx(0.9)


def test_con_token_incorrecto_el_clasificador_http_falla_con_el_motivo(equivalencia, monkeypatch, tmp_path):
    token = tmp_path / "cloud_token.txt"
    token.write_text("token-equivocado")
    monkeypatch.setattr(config, "CLOUD_URL", "https://cloud.ejemplo.test")
    monkeypatch.setattr(config, "CLOUD_TOKEN_FILE", str(token))
    crudo = RawVerdict(action_class=ActionClass.ATTACK_A, confidence=0.9, probs={}, atencion=None)
    caso = ClasificarSecuencia(FakeActionClassifier(result=crudo), IdentityArbitrationPolicy(), "m")
    app = crear_app(caso, RegistroNodos.desde_texto(f"prueba:{hash_token(TOKEN)}"), entorno="local")

    clasificador = equivalencia.ClasificadorCloudHttp()
    clasificador._transporte._cliente = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://cloud.ejemplo.test",
        headers={"Authorization": "Bearer token-equivocado"},
    )
    with pytest.raises(RuntimeError, match="timeout") as e:
        clasificador.classify(np.zeros((5, 192), dtype=np.float32), LuzSignal(True, False))
    assert "token-equivocado" not in str(e.value)
