"""scripts/crear_hash_password.py (DEPLOY05): longitud mínima y hash Argon2id."""

import importlib.util
import pathlib

import pytest
from argon2 import PasswordHasher

RUTA = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "crear_hash_password.py"
spec = importlib.util.spec_from_file_location("crear_hash_password", RUTA)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def test_rechaza_contrasena_de_menos_de_12_caracteres():
    with pytest.raises(ValueError, match="12"):
        script.validar_password("a" * 11)
    script.validar_password("a" * 12)


def test_hash_es_argon2id_y_verifica():
    hash_ = script.calcular_hash("una-clave-larga-1")

    assert hash_.startswith("$argon2id$")
    assert PasswordHasher().verify(hash_, "una-clave-larga-1")
    assert "una-clave-larga-1" not in hash_


def test_main_pide_la_contrasena_por_getpass_y_no_imprime_la_clave(monkeypatch, capsys):
    claves = iter(["una-clave-larga-1", "una-clave-larga-1"])
    monkeypatch.setattr(script.getpass, "getpass", lambda _msg: next(claves))
    monkeypatch.setattr("sys.argv", ["crear_hash_password.py"])

    assert script.main() == 0
    salida = capsys.readouterr().out
    assert salida.startswith("$argon2id$") and "una-clave-larga-1" not in salida


def test_main_rechaza_clave_corta_y_no_coincidente(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["crear_hash_password.py"])
    monkeypatch.setattr(script.getpass, "getpass", lambda _msg: "corta")
    assert script.main() == 1

    claves = iter(["una-clave-larga-1", "otra-clave-larga-2"])
    monkeypatch.setattr(script.getpass, "getpass", lambda _msg: next(claves))
    assert script.main() == 1
    assert capsys.readouterr().out == ""


def test_main_con_env_imprime_la_linea_entre_comillas_simples(monkeypatch, capsys):
    claves = iter(["una-clave-larga-1", "una-clave-larga-1"])
    monkeypatch.setattr(script.getpass, "getpass", lambda _msg: next(claves))
    monkeypatch.setattr("sys.argv", ["crear_hash_password.py", "--env"])

    assert script.main() == 0
    salida = capsys.readouterr().out.strip()
    assert salida.startswith("AUTH_PASSWORD_HASH='$argon2id$") and salida.endswith("'")
