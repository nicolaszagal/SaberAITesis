"""scripts/fog_remoto.sh (SEC02): el túnel exige ventana y se cierra solo.

Entorno simulado: `cloudflared`, `curl` y `caffeinate` son stubs en el PATH, así
que no se abre ningún túnel real. Una "hora" dura 2 s (FOG_REMOTO_SEGUNDOS_POR_HORA).
"""

import os
import pathlib
import shutil
import subprocess
import time

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def _stub(ruta: pathlib.Path, cuerpo: str) -> None:
    ruta.write_text("#!/bin/sh\n" + cuerpo)
    ruta.chmod(0o755)


@pytest.fixture
def sim(tmp_path):
    raiz = tmp_path / "backend"
    (raiz / "scripts").mkdir(parents=True)
    shutil.copy(BACKEND / "scripts" / "fog_remoto.sh", raiz / "scripts" / "fog_remoto.sh")
    _stub(raiz / "scripts" / "recordar_respaldo.sh", "exit 0\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    _stub(bin_ / "cloudflared", 'echo "https://prueba-simulada.trycloudflare.com" >&2\nexec sleep 600\n')
    _stub(bin_ / "caffeinate", "exec sleep 600\n")
    _stub(bin_ / "curl", "exit 0\n")
    entorno = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "PROXY_SHARED_TOKEN": "token-de-prueba",
        "FOG_REMOTO_SEGUNDOS_POR_HORA": "2",
        "FOG_REMOTO_SONDEO_S": "0.2",
    }

    def correr(*args):
        return subprocess.run(
            ["sh", str(raiz / "scripts" / "fog_remoto.sh"), *args],
            cwd=raiz, env=entorno, capture_output=True, text=True, timeout=60,
        )

    yield raiz, correr
    correr("stop")


def _vivo(pid_file: pathlib.Path) -> bool:
    if not pid_file.exists():
        return False
    try:
        os.kill(int(pid_file.read_text()), 0)
        return True
    except OSError:
        return False


def test_start_sin_horas_o_fuera_de_rango_se_niega_y_no_abre_el_tunel(sim):
    raiz, correr = sim

    for args in (["start"], ["start", "--horas"], ["start", "--horas", "0"],
                 ["start", "--horas", "9"], ["start", "--horas", "x"], ["start", "--horas", "-1"]):
        res = correr(*args)
        assert res.returncode == 2, args
        assert "horas" in res.stderr, args
    assert not (raiz / "datos" / "fog_remoto_tunel.pid").exists()


def test_el_tunel_se_cierra_solo_al_vencer_la_ventana(sim):
    raiz, correr = sim
    datos = raiz / "datos"

    inicio = correr("start", "--horas", "1")

    assert inicio.returncode == 0, inicio.stderr
    assert "se cierra solo a las" in inicio.stdout
    assert _vivo(datos / "fog_remoto_tunel.pid") and _vivo(datos / "fog_remoto_vigia.pid")
    estado = correr("status").stdout
    assert "Túnel activo" in estado and "Quedan" in estado and "vence a las" in estado
    pid_tunel = int((datos / "fog_remoto_tunel.pid").read_text())

    for _ in range(100):
        if not (datos / "fog_remoto_tunel.pid").exists():
            break
        time.sleep(0.1)

    assert not (datos / "fog_remoto_tunel.pid").exists()
    assert not (datos / "fog_remoto_url.txt").exists() and not (datos / "fog_remoto_vence.txt").exists()
    with pytest.raises(OSError):
        os.kill(pid_tunel, 0)
    assert correr("status").stdout.strip() == "Túnel detenido."


def test_stop_manual_cierra_tambien_el_vigia(sim):
    raiz, correr = sim
    datos = raiz / "datos"
    assert correr("start", "--horas", "8").returncode == 0
    pid_vigia = int((datos / "fog_remoto_vigia.pid").read_text())

    assert correr("stop").returncode == 0

    time.sleep(0.5)
    with pytest.raises(OSError):
        os.kill(pid_vigia, 0)
    assert not any(datos.glob("fog_remoto_*.pid"))


def test_al_arrancar_avisa_si_quedaron_pid_viejos(sim):
    raiz, correr = sim
    datos = raiz / "datos"
    datos.mkdir()
    (datos / "fog_remoto_tunel.pid").write_text("999999")
    (datos / "fog_remoto_url.txt").write_text("https://vieja.trycloudflare.com")

    res = correr("start", "--horas", "1")

    assert res.returncode == 0, res.stderr
    assert "el último 'stop' no corrió" in res.stderr
    assert "vieja" not in (datos / "fog_remoto_url.txt").read_text()


def test_status_con_restos_sin_proceso_lo_dice(sim):
    raiz, correr = sim
    datos = raiz / "datos"
    datos.mkdir()
    (datos / "fog_remoto_tunel.pid").write_text("999999")

    assert "el último 'stop' no corrió" in correr("status").stdout
