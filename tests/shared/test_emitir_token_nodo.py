"""scripts/emitir_token_nodo.sh (DEPLOY11): token en archivo 600, solo `nombre:hash` por pantalla."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from cloud.infrastructure.api.nodos import RegistroNodos, hash_token

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "emitir_token_nodo.sh"


def _emitir(tmp_path, *args):
    return subprocess.run(
        ["sh", str(SCRIPT), *args], capture_output=True, text=True,
        env={**os.environ, "TOKENS_DIR": str(tmp_path / "tokens")},
    )


def test_emite_archivo_600_y_solo_imprime_nombre_y_hash(tmp_path):
    r = _emitir(tmp_path, "revisor-1")
    assert r.returncode == 0
    archivo = tmp_path / "tokens" / "revisor-1.token"
    token = archivo.read_text().strip()
    assert stat.S_IMODE(archivo.stat().st_mode) == 0o600
    assert stat.S_IMODE(archivo.parent.stat().st_mode) == 0o700
    assert token not in r.stdout and token not in r.stderr
    assert r.stdout.strip() == f"revisor-1:{hash_token(token)}"
    assert RegistroNodos.desde_texto(r.stdout).autenticar(token) == "revisor-1"


def test_no_reemplaza_sin_forzar_y_con_forzar_cambia_el_token(tmp_path):
    _emitir(tmp_path, "n1")
    archivo = tmp_path / "tokens" / "n1.token"
    primero = archivo.read_text()
    assert _emitir(tmp_path, "n1").returncode == 1
    assert archivo.read_text() == primero
    assert _emitir(tmp_path, "n1", "--forzar").returncode == 0
    assert archivo.read_text() != primero


@pytest.mark.parametrize("nombre", ["", "Mal", "con espacio", "-x", "a" * 33, "../fuga"])
def test_rechaza_nombres_invalidos(tmp_path, nombre):
    r = _emitir(tmp_path, nombre)
    assert r.returncode == 2
    assert not (tmp_path / "tokens").exists() or not list((tmp_path / "tokens").iterdir())


def test_rechaza_una_carpeta_dentro_del_repo():
    dentro = SCRIPT.parents[1] / "no-debe-crearse"
    r = subprocess.run(["sh", str(SCRIPT), "x1"], capture_output=True, text=True,
                       env={**os.environ, "TOKENS_DIR": str(dentro)})
    try:
        assert r.returncode == 1 and "dentro del repo" in r.stderr
        assert not any(dentro.glob("*.token"))
    finally:
        if dentro.exists():
            dentro.rmdir()
