"""DEPLOY11 — modo remoto del instalador: configurar-remoto e importar-token."""

import os
import pathlib
import stat
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / "scripts"))

import instalador  # noqa: E402

TOKEN = "t" * 43


def _modo(ruta):
    return stat.S_IMODE(os.stat(ruta).st_mode)


def test_configurar_remoto_escribe_transporte_url_y_origen_del_frontend(tmp_path):
    archivo = tmp_path / "s" / "fog_remoto.env"
    valores = instalador.configurar_remoto(archivo, "https://cloud.up.railway.app/", "https://front.up.railway.app/ruta?x=1")
    assert valores == {
        "CLOUD_TRANSPORTE": "http", "CLOUD_URL": "https://cloud.up.railway.app",
        "CORS_ORIGINS": "https://front.up.railway.app",
    }
    assert set(archivo.read_text().splitlines()) == {
        "CLOUD_TRANSPORTE=http", "CLOUD_URL=https://cloud.up.railway.app", "CORS_ORIGINS=https://front.up.railway.app",
    }
    assert _modo(archivo) == 0o600


def test_configurar_remoto_conserva_lo_demas_actualiza_lo_propio_y_quita_el_token_de_proxy(tmp_path):
    archivo = tmp_path / "fog_remoto.env"
    archivo.write_text("AUTH_USER=revisor\nCLOUD_URL=https://viejo.example\nPROXY_SHARED_TOKEN=abc\nCORS_ORIGINS=https://x\n")
    instalador.configurar_remoto(archivo, "https://cloud.test", "https://front.test")
    lineas = archivo.read_text().splitlines()
    assert "AUTH_USER=revisor" in lineas
    assert "CLOUD_URL=https://cloud.test" in lineas and lineas.count("CLOUD_URL=https://cloud.test") == 1
    assert not any(linea.startswith("PROXY_SHARED_TOKEN") for linea in lineas)
    assert "https://viejo.example" not in archivo.read_text()


@pytest.mark.parametrize("cloud, front", [
    ("http://cloud.test", "https://front.test"),
    ("https://cloud.test", "http://front.test"),
    ("https://u:Secreta7@cloud.test", "https://front.test"),
    ("cloud.test", "https://front.test"),
])
def test_configurar_remoto_rechaza_urls_no_https_y_no_filtra_credenciales(tmp_path, cloud, front):
    archivo = tmp_path / "fog_remoto.env"
    with pytest.raises(ValueError) as e:
        instalador.configurar_remoto(archivo, cloud, front)
    assert "Secreta7" not in str(e.value)
    assert not archivo.exists()


def test_configurar_remoto_admite_localhost_en_pruebas(tmp_path):
    valores = instalador.configurar_remoto(tmp_path / "e.env", "http://localhost:8002", "https://front.test")
    assert valores["CLOUD_URL"] == "http://localhost:8002"


def test_importar_token_copia_con_600_y_sin_mostrarlo(tmp_path):
    origen = tmp_path / "revisor.token"
    origen.write_text(TOKEN + "\n")
    destino = tmp_path / ".secrets" / "cloud_token.txt"
    assert instalador.importar_token(origen, destino) is False
    assert destino.read_text().strip() == TOKEN
    assert _modo(destino) == 0o600 and _modo(destino.parent) == 0o700


def test_importar_token_indica_si_reemplaza_uno_distinto(tmp_path):
    destino = tmp_path / "cloud_token.txt"
    for nuevo, esperado in (("a" * 40, False), ("a" * 40, False), ("b" * 40, True)):
        origen = tmp_path / "t.token"
        origen.write_text(nuevo)
        assert instalador.importar_token(origen, destino) is esperado
    assert destino.read_text().strip() == "b" * 40


@pytest.mark.parametrize("contenido", ["", "\n", "corto", "dos tokens " + "x" * 40, "linea1\nlinea2" + "x" * 40])
def test_importar_token_rechaza_archivos_que_no_son_un_token_sin_mostrar_su_contenido(tmp_path, contenido):
    origen = tmp_path / "t.token"
    origen.write_text(contenido)
    with pytest.raises(ValueError) as e:
        instalador.importar_token(origen, tmp_path / "d.txt")
    assert contenido.strip() == "" or contenido.strip() not in str(e.value)
    assert not (tmp_path / "d.txt").exists()


def test_cli_importar_token_no_imprime_el_token(tmp_path):
    origen = tmp_path / "t.token"
    origen.write_text(TOKEN)
    r = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "instalador.py"), "importar-token", str(origen),
         "--destino", str(tmp_path / "cloud_token.txt")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0 and r.stdout.strip() == "instalado"
    assert TOKEN not in r.stdout + r.stderr
