"""Traducción de clases entre el modelo y el esquema: solo la hacen los
adaptadores de persistencia (fog/infrastructure/persistence/postgres)."""

import pytest

from fog.domain.models import CLASES_MODELO
from fog.infrastructure.persistence.postgres.vocabulario import (
    clase_a_esquema,
    clase_a_modelo,
    probabilidades_a_esquema,
    probabilidades_a_modelo,
)

ESQUEMA = ("AtaqueA", "AtaqueB", "ContraataqueA", "ContraataqueB", "RiposteA", "RiposteB")


def test_cada_clase_del_modelo_ida_y_vuelta():
    assert [clase_a_esquema(c) for c in CLASES_MODELO] == list(ESQUEMA)
    assert [clase_a_modelo(c) for c in ESQUEMA] == list(CLASES_MODELO)


def test_none_pasa_sin_cambios():
    assert clase_a_esquema(None) is None
    assert clase_a_modelo(None) is None
    assert probabilidades_a_esquema(None) is None
    assert probabilidades_a_modelo(None) is None


def test_las_probabilidades_traducen_solo_las_llaves():
    modelo = {"AttackA": 0.7, "ContrattackB": 0.3}

    esquema = probabilidades_a_esquema(modelo)

    assert esquema == {"AtaqueA": 0.7, "ContraataqueB": 0.3}
    assert probabilidades_a_modelo(esquema) == modelo


@pytest.mark.parametrize("clase", ["AtaqueA", "Inventada", ""])
def test_una_clase_del_esquema_no_es_del_modelo(clase):
    with pytest.raises(ValueError):
        clase_a_esquema(clase)


@pytest.mark.parametrize("clase", ["AttackA", "Inventada", ""])
def test_una_clase_del_modelo_no_es_del_esquema(clase):
    with pytest.raises(ValueError):
        clase_a_modelo(clase)
