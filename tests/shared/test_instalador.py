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
                                       ("AUTH_USER", "AUTH_PASSWORD_HASH", "AUTH_JWT_SECRET", "RESPALDO_DIR")})
    assert "POSTGRES_PASSWORD" not in plantilla.replace("# La contraseña de PostgreSQL NO va aquí", "")  # fuente única: .secrets


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


# --- Configuración real del Mac: .env mínimo + .secrets/fog_remoto.env ---------------------


def _cargar(tmp_path, explicito: str | None = None, remoto: bool = False):
    (tmp_path / ".secrets").mkdir(exist_ok=True)
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=desde_env\nRESPALDO_DIR=/r\n")
    (tmp_path / ".secrets" / "fog_remoto.env").write_text("AUTH_USER=maestro\nPOSTGRES_PASSWORD=desde_secretos\nENTORNO=remoto\n")
    pre = f"ENV_FILE={explicito}; ENV_FILE_EXPLICITO=1;" if explicito else "ENV_FILE=.env;"
    pre += f" MODO_REMOTO={1 if remoto else 0};"
    cmd = f'{pre} . {BACKEND}/scripts/lib_fog_env.sh; cargar_archivos_env; aplicar_modo; echo "$AUTH_USER|$POSTGRES_PASSWORD|$RESPALDO_DIR|$ENTORNO"'
    return subprocess.run(["sh", "-c", cmd], cwd=tmp_path, capture_output=True, text=True).stdout.strip()


def test_por_defecto_es_local_y_no_lee_fog_remoto_env(tmp_path):
    assert _cargar(tmp_path) == "|desde_env|/r|local"


def test_con_remoto_carga_env_y_encima_fog_remoto_env_y_fija_entorno_remoto(tmp_path):
    assert _cargar(tmp_path, remoto=True) == "maestro|desde_secretos|/r|remoto"


def test_la_clave_de_postgres_sale_de_secrets_y_manda_sobre_el_env(tmp_path):
    (tmp_path / ".secrets").mkdir(exist_ok=True)
    (tmp_path / ".secrets" / "postgres_password.txt").write_text("deSecrets\n")
    assert _cargar(tmp_path) == "|deSecrets|/r|local"
    assert _cargar(tmp_path, remoto=True) == "maestro|deSecrets|/r|remoto"


def test_fog_nativo_local_y_remoto_con_mostrar(tmp_path):
    import os
    env = tmp_path / "e.env"
    env.write_text("RESPALDO_DIR=/r\nPOSTGRES_PASSWORD=xyz\nREDIS_URL_REMOTO=rediss://u:clave@h/0\n")
    base = {**os.environ, "ENV_FILE": str(env), "DATOS_DIR": str(tmp_path / "d"), "VENV_DIR": str(BACKEND / ".venv"),
            "SECRETS_DIR": str(tmp_path / "nada"), "ENTORNO": "remoto"}
    run = lambda *a: subprocess.run(["sh", str(BACKEND / "scripts" / "fog_nativo.sh"), *a],
                                    cwd=BACKEND, env=base, capture_output=True, text=True)
    local = run("--mostrar")
    assert local.returncode == 0, local.stderr
    assert "modo: local" in local.stdout and "ENTORNO=local" in local.stdout
    assert "BIND_HOST=0.0.0.0" in local.stdout and "redis://127.0.0.1" in local.stdout
    assert "clave" not in local.stdout and "xyz" not in local.stdout
    remoto = run("--remoto", "--mostrar")
    assert "modo: remoto" in remoto.stdout and "ENTORNO=remoto" in remoto.stdout
    assert "BIND_HOST=127.0.0.1" in remoto.stdout and "rediss://***@h/0" in remoto.stdout
    assert remoto.returncode == 1 and "probar --remoto" in remoto.stderr  # sin `probar` aprobada: bloqueo
    assert run("--otra").returncode == 2


def test_instalar_fog_modo_local_por_defecto_y_remoto_explicito(tmp_path):
    import os
    sec = tmp_path / "fog_remoto.env"
    sec.write_text("ENTORNO=remoto\n")
    env = {**os.environ, "ENV_SECRETO": str(sec), "SECRETS_DIR": str(tmp_path / "nada")}
    run = lambda *a: subprocess.run(["sh", str(BACKEND / "scripts" / "instalar_fog.sh"), *a],
                                    cwd=BACKEND, env=env, capture_output=True, text=True).stdout
    assert "modo: local" in run("modo") and str(sec) not in run("modo")
    assert "modo: remoto" in run("modo", "--remoto") and str(sec) in run("modo", "--remoto")


def test_con_env_file_explicito_usa_solo_ese_archivo(tmp_path):
    assert _cargar(tmp_path, explicito=".env") == "|desde_env|/r|local"


def test_sin_ningun_archivo_no_falla_y_no_carga_nada(tmp_path):
    cmd = f'ENV_FILE=.env; . {BACKEND}/scripts/lib_fog_env.sh; [ -z "$(archivos_env)" ] && echo vacio'
    assert subprocess.run(["sh", "-c", cmd], cwd=tmp_path, capture_output=True, text=True).stdout.strip() == "vacio"


def test_instalar_no_exige_auth_en_el_env_minimo():
    fuente = (BACKEND / "scripts" / "instalar_fog.sh").read_text()
    assert "archivos_env" in fuente and "ENV_FILE_EXPLICITO" in fuente
    assert "--env-file" not in fuente


def test_verificar_clave_postgres_acepta_la_de_secrets_y_rechaza_sabre_local(tmp_path):
    """Con un Postgres desechable cuya clave es la de .secrets: esa entra y `sabre_local` no."""
    import os
    import shutil
    import time
    if not shutil.which("docker") or not shutil.which("psql"):
        pytest.skip("hace falta docker y psql")
    clave = "ClaveDePrueba123"
    (tmp_path / "postgres_password.txt").write_text(clave)
    nombre = f"pg-clave-{os.getpid()}"
    r = subprocess.run(["docker", "run", "-d", "--rm", "--name", nombre, "-e", "POSTGRES_USER=sabre",
                        "-e", f"POSTGRES_PASSWORD={clave}", "-e", "POSTGRES_DB=sabre", "-p", "127.0.0.1:5459:5432",
                        "postgres:16-alpine"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"docker no disponible: {r.stderr[:80]}")
    try:
        for _ in range(40):
            if subprocess.run(["docker", "exec", nombre, "pg_isready", "-h", "127.0.0.1", "-U", "sabre"],
                              capture_output=True).returncode == 0:
                break
            time.sleep(0.5)
        time.sleep(1)
        env = {**os.environ, "SECRETS_DIR": str(tmp_path)}
        ok = subprocess.run(["sh", str(BACKEND / "scripts" / "verificar_clave_postgres.sh"), "5459"],
                            cwd=BACKEND, env=env, capture_output=True, text=True)
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert "de .secrets: ACEPTADA" in ok.stdout and "(sabre_local): rechazada" in ok.stdout
        assert clave not in ok.stdout + ok.stderr  # nunca imprime la clave
        (tmp_path / "postgres_password.txt").write_text("otraClave999")
        mal = subprocess.run(["sh", str(BACKEND / "scripts" / "verificar_clave_postgres.sh"), "5459"],
                             cwd=BACKEND, env=env, capture_output=True, text=True)
        assert mal.returncode == 1 and "RECHAZADA" in mal.stdout
    finally:
        subprocess.run(["docker", "stop", nombre], capture_output=True)


# --- obtener_archivo_modelo (DOC01: instalación en un clon sin ../dataset) ------


def _sha(contenido: bytes) -> str:
    import hashlib

    return hashlib.sha256(contenido).hexdigest()


def test_obtener_modelo_copia_del_repositorio_y_verifica(tmp_path):
    repo = tmp_path / "repo_dataset"
    (repo / "lstm_6class").mkdir(parents=True)
    (repo / "lstm_6class" / "stats.npz").write_bytes(b"estadisticas")
    destino = tmp_path / "dataset"
    como = instalador.obtener_archivo_modelo(destino, "lstm_6class/stats.npz", _sha(b"estadisticas"), repo)
    assert como == "copiado del repositorio"
    assert (destino / "lstm_6class" / "stats.npz").read_bytes() == b"estadisticas"


def test_obtener_modelo_descarga_si_no_esta_en_el_repositorio(tmp_path):
    fuente = tmp_path / "pesos.pt"
    fuente.write_bytes(b"pesos")
    destino = tmp_path / "dataset"
    como = instalador.obtener_archivo_modelo(destino, "yolov8x-pose.pt", _sha(b"pesos"), None, fuente.as_uri())
    assert como == "descargado"
    assert (destino / "yolov8x-pose.pt").read_bytes() == b"pesos"


def test_obtener_modelo_hash_distinto_no_deja_el_archivo(tmp_path):
    fuente = tmp_path / "pesos.pt"
    fuente.write_bytes(b"otros pesos")
    destino = tmp_path / "dataset"
    with pytest.raises(ValueError, match="no coincide"):
        instalador.obtener_archivo_modelo(destino, "yolov8x-pose.pt", _sha(b"pesos"), None, fuente.as_uri())
    assert not (destino / "yolov8x-pose.pt").exists()
    assert not (destino / "yolov8x-pose.pt.parte").exists()


def test_obtener_modelo_existente_no_se_sobrescribe(tmp_path):
    destino = tmp_path / "dataset"
    destino.mkdir()
    (destino / "a.bin").write_bytes(b"distinto")
    with pytest.raises(ValueError, match="No se sobrescribe"):
        instalador.obtener_archivo_modelo(destino, "a.bin", _sha(b"esperado"), None, None)
    assert (destino / "a.bin").read_bytes() == b"distinto"


def test_obtener_modelo_sin_origen_falla(tmp_path):
    with pytest.raises(FileNotFoundError):
        instalador.obtener_archivo_modelo(tmp_path / "dataset", "x.bin", _sha(b"x"), None, None)


# --- mensaje final de `instalar` (DOC01) ---------------------------------------


def test_mensaje_final_local_con_cpu_no_exige_probar():
    texto = instalador.mensaje_final_instalacion(remoto=False, dispositivo="cpu")
    assert "NO ESTÁ LISTO" not in texto
    assert "fog_nativo.sh" in texto


@pytest.mark.parametrize("remoto,dispositivo", [(True, "cpu"), (False, "mps")])
def test_mensaje_final_exige_probar_donde_el_bloqueo_la_exige(remoto, dispositivo):
    assert "probar" in instalador.mensaje_final_instalacion(remoto, dispositivo)
    assert instalador.evaluar_bloqueo(None, "", dispositivo, remoto)[0] is False
