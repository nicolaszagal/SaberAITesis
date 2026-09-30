"""Precalentamiento de Cloud (F-027): una inferencia con ceros al arrancar,
sin efectos observables fuera del log, y sin arranque si falla."""

import logging

import numpy as np
import pytest
import torch

import cloud.main as cloud_main
from cloud.application.classify_and_publish import ClassifyAndPublish
from cloud.infrastructure.classifier.lstm6class_adapter import (
    PRECALENTAMIENTO_FRAMES, LSTM6ClassAdapter,
)
from shared import config
from tests.cloud.fakes import (
    FakeActionClassifier, FakeFeatureConsumer, FakeVerdictPublisher,
    IdentityArbitrationPolicy,
)
from tests.cloud.test_lstm6class_adapter import _write_synthetic_run

_MODELO = "lstm_6class/run/best_model.pt"


def _caso_de_uso(classifier, publisher=None, consumer=None) -> ClassifyAndPublish:
    return ClassifyAndPublish(
        consumer=consumer or FakeFeatureConsumer(items=[]),
        classifier=classifier,
        arbitration=IdentityArbitrationPolicy(),
        publisher=publisher or FakeVerdictPublisher(),
        modelo_version_name=_MODELO,
    )


def test_adaptador_infiere_una_secuencia_de_ceros_192(tmp_path):
    _write_synthetic_run(tmp_path)
    adapter = LSTM6ClassAdapter(run_dir=str(tmp_path), device=torch.device("cpu"))
    entradas = []
    original = adapter._model.forward

    def espia(x, *args, **kwargs):
        entradas.append(x.detach().clone())
        return original(x, *args, **kwargs)

    adapter._model.forward = espia

    assert adapter.precalentar() is None  # el resultado se descarta

    assert len(entradas) == 1
    assert entradas[0].shape == (1, PRECALENTAMIENTO_FRAMES, 192)
    assert not np.any(entradas[0].numpy())


def test_precalentar_registra_info_con_duracion_y_no_publica(caplog):
    classifier = FakeActionClassifier()
    publisher = FakeVerdictPublisher()
    consumer = FakeFeatureConsumer(items=[])

    with caplog.at_level(logging.INFO, logger="cloud.application"):
        _caso_de_uso(classifier, publisher, consumer).precalentar()

    assert classifier.precalentamientos == 1
    assert classifier.calls == []  # no pasa por classify: no entra a las métricas
    assert publisher.published == []
    assert consumer.acked == []
    registros = [r for r in caplog.records if "modelo precalentado" in r.getMessage()]
    assert len(registros) == 1
    assert registros[0].levelno == logging.INFO
    assert " ms" in registros[0].getMessage()


def test_precalentar_propaga_la_falla():
    classifier = FakeActionClassifier(raises=RuntimeError("modelo roto"))

    with pytest.raises(RuntimeError, match="modelo roto"):
        _caso_de_uso(classifier).precalentar()


async def test_cloud_no_arranca_si_el_precalentamiento_falla(monkeypatch):
    consumiendo = []

    class CasoDeUso:
        def precalentar(self):
            raise RuntimeError("modelo roto")

        async def run_forever(self):
            consumiendo.append(True)

    class ContenedorFalso:
        def __init__(self):
            self.config = type("C", (), {
                "redis_url": type("P", (), {"from_value": lambda *a: None})(),
                "model_run_dir": type("P", (), {"from_value": lambda *a: None})(),
            })()

        def classify_and_publish(self):
            return CasoDeUso()

    monkeypatch.setattr(config, "MODEL_RUN_DIR", "/ruta/run")
    monkeypatch.setattr(cloud_main, "Container", ContenedorFalso)

    with pytest.raises(RuntimeError, match="modelo roto"):
        await cloud_main.main()
    assert consumiendo == []
