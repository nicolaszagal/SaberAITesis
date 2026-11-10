"""SEC02: en modo remoto Fog solo escucha en loopback; el modo piloto local no cambia."""

import pathlib
import subprocess

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def _bind(**entorno):
    return subprocess.run(
        ["sh", "-c", ". scripts/lib_fog_bind.sh && fog_bind_host"],
        cwd=BACKEND, env={"PATH": "/usr/bin:/bin", **entorno}, capture_output=True, text=True,
    )


def test_modo_remoto_escucha_solo_en_loopback_por_defecto():
    res = _bind(ENTORNO="remoto")

    assert res.returncode == 0 and res.stdout.strip() == "127.0.0.1"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "100.101.102.103", "::"])
def test_modo_remoto_rechaza_cualquier_direccion_que_no_sea_loopback(host):
    res = _bind(ENTORNO="remoto", FOG_BIND_HOST=host)

    assert res.returncode == 1 and "loopback" in res.stderr and res.stdout == ""


def test_modo_remoto_admite_loopback_explicito():
    assert _bind(ENTORNO="remoto", FOG_BIND_HOST="127.0.0.1").stdout.strip() == "127.0.0.1"


@pytest.mark.parametrize("entorno", [{}, {"ENTORNO": "local"}])
def test_modo_piloto_local_sigue_en_0_0_0_0_para_el_frontend_en_docker(entorno):
    assert _bind(**entorno).stdout.strip() == "0.0.0.0"
    assert _bind(**entorno, FOG_BIND_HOST="127.0.0.1").stdout.strip() == "127.0.0.1"


def test_fog_nativo_usa_la_funcion_y_ya_no_fija_0_0_0_0():
    fuente = (BACKEND / "scripts" / "fog_nativo.sh").read_text()

    assert "fog_bind_host" in fuente and '--host "$BIND_HOST"' in fuente
    assert "--host 0.0.0.0" not in fuente
    assert "VENV_DIR" in fuente and "DATASET_DIR" in fuente
