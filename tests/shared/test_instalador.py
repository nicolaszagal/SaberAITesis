"""DEPLOY10 — lógica aislable de scripts/instalar_fog.sh: manifiesto, equivalencia, bloqueo y compose."""

import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / "scripts"))

import instalador  # noqa: E402


def _paquete(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.bin").write_bytes(b"uno")
    (tmp_path / "y.txt").write_text("dos")
    instalador.crear_manifiesto(tmp_path)
    return tmp_path


# --- manifiesto ----------------------------------------------------------------


def test_manifiesto_correcto_no_da_problemas(tmp_path):
    assert instalador.verificar_manifiesto(_paquete(tmp_path)) == []


def test_manifiesto_detecta_archivo_alterado(tmp_path):
    p = _paquete(tmp_path)
    (p / "y.txt").write_text("alterado")
    assert instalador.verificar_manifiesto(p) == ["hash distinto: y.txt"]


def test_manifiesto_detecta_archivo_faltante(tmp_path):
    p = _paquete(tmp_path)
    (p / "a" / "x.bin").unlink()
    assert instalador.verificar_manifiesto(p) == ["falta a/x.bin"]


def test_manifiesto_estricto_detecta_archivo_extra_y_no_estricto_lo_permite(tmp_path):
    p = _paquete(tmp_path)
    (p / "extra.txt").write_text("colado")
    assert instalador.verificar_manifiesto(p) == ["archivo fuera del manifiesto: extra.txt"]
    assert instalador.verificar_manifiesto(p, estricto=False) == []


def test_manifiesto_ausente_o_vacio_o_malformado(tmp_path):
    assert "falta MANIFEST.sha256" in instalador.verificar_manifiesto(tmp_path)[0]
    (tmp_path / "MANIFEST.sha256").write_text("")
    assert "vacío" in instalador.verificar_manifiesto(tmp_path)[0]
    (tmp_path / "MANIFEST.sha256").write_text("esto no es un hash\n")
    assert "formato inválido" in instalador.verificar_manifiesto(tmp_path)[0]


def test_manifiesto_acepta_el_formato_de_shasum(tmp_path):
    (tmp_path / "f").write_text("hola")
    h = instalador.sha256_archivo(tmp_path / "f")
    (tmp_path / "M").write_text(f"{h}  f\n")
    assert instalador.verificar_manifiesto(tmp_path, nombre="M") == []


# --- comparación de salidas ------------------------------------------------------


def _salida(clase="AttackA", p=0.9, kp="h1"):
    return {"clase": clase, "probabilidades": {"AttackA": p, "AttackB": round(1 - p, 4)}, "keypoints_sha256": kp}


def test_equivalencia_aprobada_con_diferencia_dentro_de_la_cota():
    esperado = {"c1": _salida(), "c2": _salida("AttackB", 0.2)}
    obtenido = {"c1": _salida(p=0.9004, kp="otro"), "c2": _salida("AttackB", 0.2)}
    r = instalador.comparar_salidas(esperado, obtenido, cota=0.001)
    assert r["aprobado"] and r["clases_iguales"] == 2 and r["diferencia_maxima"] == pytest.approx(0.0004)
    assert r["keypoints_iguales"] == 1  # informativo: no decide la aprobación


def test_equivalencia_rechaza_clase_distinta():
    r = instalador.comparar_salidas({"c1": _salida()}, {"c1": _salida("AttackB")}, cota=1.0)
    assert not r["aprobado"] and "misma clase en 0/1" in r["motivo"]


def test_equivalencia_rechaza_diferencia_sobre_la_cota():
    r = instalador.comparar_salidas({"c1": _salida()}, {"c1": _salida(p=0.95)}, cota=0.01)
    assert not r["aprobado"] and "supera la cota" in r["motivo"]


def test_equivalencia_sin_cota_confirmada_no_aprueba_ni_con_salidas_identicas():
    r = instalador.comparar_salidas({"c1": _salida()}, {"c1": _salida()}, cota=None)
    assert not r["aprobado"] and "cota" in r["motivo"]


def test_equivalencia_clip_faltante_o_con_error_no_aprueba():
    esperado = {"c1": _salida(), "c2": _salida()}
    r = instalador.comparar_salidas(esperado, {"c1": _salida(), "c2": {"error": "no abre"}}, cota=1.0)
    assert not r["aprobado"] and "c2" in r["motivo"]
    r = instalador.comparar_salidas(esperado, {"c1": _salida()}, cota=1.0)
    assert not r["aprobado"] and r["clips"]["c2"]["error"] == "clip no procesado"


# --- base destino con revisiones --------------------------------------------------


@pytest.mark.parametrize("conteos,esperado", [("0,0,0,0", False), ("0,0,0,7", False), ("2,2,1,1", True)])
def test_base_tiene_revisiones(conteos, esperado):
    assert instalador.base_tiene_revisiones(conteos) is esperado


@pytest.mark.parametrize("conteos", ["", "1,2,3", "a,b,c,d", "1,2,3,4,5"])
def test_base_tiene_revisiones_rechaza_formato_inesperado(conteos):
    with pytest.raises(ValueError):
        instalador.base_tiene_revisiones(conteos)


def test_cli_base_vacia_devuelve_codigo_de_salida():
    cmd = [sys.executable, str(BACKEND / "scripts" / "instalador.py"), "base-vacia"]
    assert subprocess.run([*cmd, "0,0,0,0"]).returncode == 0
    assert subprocess.run([*cmd, "3,0,0,0"]).returncode == 1


# --- bloqueo de fog_nativo.sh -----------------------------------------------------

OK = {"aprobado": True, "commit": "abc123", "dispositivo": "cpu"}


def test_local_con_cpu_no_exige_equivalencia():
    assert instalador.evaluar_bloqueo(None, "abc123", "cpu", remoto=False)[0]


def test_remoto_sin_reporte_no_arranca():
    assert not instalador.evaluar_bloqueo(None, "abc123", "cpu", remoto=True)[0]


def test_remoto_con_prueba_no_aprobada_no_arranca():
    permitido, motivo = instalador.evaluar_bloqueo({**OK, "aprobado": False, "motivo": "misma clase en 9/10"}, "abc123", "cpu", True)
    assert not permitido and "9/10" in motivo


def test_remoto_con_prueba_de_otro_commit_no_arranca():
    assert not instalador.evaluar_bloqueo({**OK, "commit": "zzz999"}, "abc123", "cpu", True)[0]


def test_remoto_con_prueba_aprobada_del_mismo_commit_arranca():
    assert instalador.evaluar_bloqueo(OK, "abc123", "cpu", True)[0]


def test_dispositivo_distinto_de_cpu_exige_prueba_con_ese_dispositivo_tambien_en_local():
    assert not instalador.evaluar_bloqueo(OK, "abc123", "mps", remoto=False)[0]
    assert instalador.evaluar_bloqueo({**OK, "dispositivo": "mps"}, "abc123", "mps", remoto=False)[0]


def test_cli_bloqueo_usa_el_reporte_mas_reciente(tmp_path):
    ev = tmp_path / "evidencia"
    ev.mkdir()
    (ev / "equivalencia_mac_20261118T000000Z.json").write_text(json.dumps(OK))
    (ev / "equivalencia_mac_20261119T000000Z.json").write_text(json.dumps({**OK, "aprobado": False, "motivo": "x"}))
    cmd = [sys.executable, str(BACKEND / "scripts" / "instalador.py"), "bloqueo", "--datos", str(tmp_path),
           "--commit", "abc123", "--remoto"]
    assert subprocess.run(cmd, capture_output=True).returncode == 1


def test_fog_nativo_consulta_el_bloqueo_antes_de_arrancar():
    fuente = (BACKEND / "scripts" / "fog_nativo.sh").read_text()
    assert "instalador.py bloqueo" in fuente
    assert fuente.index("instalador.py bloqueo") < fuente.index("exec uvicorn")


# --- restauración sin pisar ---------------------------------------------------------


def test_fusionar_no_pisa_ni_borra(tmp_path):
    origen, destino = tmp_path / "o", tmp_path / "d"
    (origen / "s").mkdir(parents=True)
    destino.mkdir()
    (origen / "s" / "nuevo").write_text("n")
    (origen / "igual").write_text("i")
    (origen / "choque").write_text("de origen")
    (destino / "igual").write_text("i")
    (destino / "choque").write_text("del destino")
    (destino / "propio").write_text("p")
    r = instalador.fusionar_sin_pisar(origen, destino)
    assert r == {"copiados": ["s/nuevo"], "iguales": ["igual"], "conflictos": ["choque"]}
    assert (destino / "choque").read_text() == "del destino"
    assert (destino / "propio").exists()


# --- .env desde la plantilla -----------------------------------------------------------


def test_generar_env_rellena_solo_claves_vacias_y_no_toca_comentarios():
    plantilla = "# POSTGRES_HOST_PORT=5436\nAUTH_USER=\nAUTH_PASSWORD_HASH=''\nENTORNO=local\n"
    texto = instalador.generar_env(plantilla, {"AUTH_USER": "ana", "AUTH_PASSWORD_HASH": "'$argon2id$x'"})
    assert texto == "# POSTGRES_HOST_PORT=5436\nAUTH_USER=ana\nAUTH_PASSWORD_HASH='$argon2id$x'\nENTORNO=local\n"


def test_generar_env_falla_si_falta_la_clave():
    with pytest.raises(ValueError, match="RESPALDO_DIR"):
        instalador.generar_env("AUTH_USER=\n", {"RESPALDO_DIR": "/x"})


def test_la_plantilla_real_tiene_todas_las_claves_que_rellena_instalar():
    plantilla = (BACKEND / ".env.example").read_text()
    instalador.generar_env(plantilla, {k: "v" for k in
                                       ("POSTGRES_PASSWORD", "AUTH_USER", "AUTH_PASSWORD_HASH", "AUTH_JWT_SECRET", "RESPALDO_DIR")})


# --- Docker Compose: una sola función común -----------------------------------------------


def _con_stubs(tmp_path, plugin: bool, binario: bool):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f'#!/bin/sh\n[ "$1 $2" = "compose version" ] && exit {0 if plugin else 1}\nexit 0\n')
    docker.chmod(0o755)
    if binario:
        dc = bin_dir / "docker-compose"
        dc.write_text("#!/bin/sh\necho docker-compose \"$@\"\n")
        dc.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "COMPOSE_CMD": ""}


def _detectar(env):
    return subprocess.run(["sh", "-c", f'. {BACKEND}/scripts/lib_compose.sh; detectar_compose && echo "$COMPOSE_CMD"'],
                          env=env, capture_output=True, text=True)


def test_compose_prefiere_el_plugin(tmp_path):
    assert _detectar(_con_stubs(tmp_path, plugin=True, binario=True)).stdout.strip() == "docker compose"


def test_compose_usa_el_binario_suelto_si_no_hay_plugin(tmp_path):
    assert _detectar(_con_stubs(tmp_path, plugin=False, binario=True)).stdout.strip() == "docker-compose"


def test_compose_sin_ninguno_falla(tmp_path):
    r = _detectar(_con_stubs(tmp_path, plugin=False, binario=False))
    assert r.returncode != 0 and r.stdout.strip() == ""


def test_ningun_script_escribe_docker_compose_a_mano():
    permitido = {"lib_compose.sh", "instalar_fog.sh"}  # el texto de los mensajes de ayuda
    for sh in (BACKEND / "scripts").glob("*.sh"):
        if sh.name in permitido:
            continue
        for n, linea in enumerate(sh.read_text().splitlines(), start=1):
            if linea.lstrip().startswith("#") or 'echo "' in linea:
                continue
            assert not re.search(r"docker compose|docker-compose(?![.\w])", linea), f"{sh.name}:{n}: {linea}"
