"""FIX03 — respaldo verificado de una sesión de validación (DEF-31).

Corre `scripts/respaldar_sesion.sh` contra un PostgreSQL real en un contenedor propio de este
módulo (el script entra al contenedor con `docker exec`, así que no sirven `TEST_DATABASE_URL`
ni testcontainers). Sin Docker se omiten.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from tests.fog.conftest import BACKEND

SCRIPT = BACKEND / "scripts" / "respaldar_sesion.sh"
RECORDAR = BACKEND / "scripts" / "recordar_respaldo.sh"
USUARIO, BASE = "sabre", "sabre"


def _docker(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False, **kw)


@pytest.fixture(scope="module")
def contenedor_pg():
    """Contenedor postgres:16-alpine propio del módulo; devuelve (nombre, url asyncpg)."""
    nombre = f"sabre-test-respaldo-{uuid.uuid4().hex[:8]}"
    r = _docker(
        "run", "-d", "--rm", "--name", nombre, "-e", f"POSTGRES_USER={USUARIO}", "-e", "POSTGRES_PASSWORD=t",
        "-e", f"POSTGRES_DB={BASE}", "-p", "127.0.0.1::5432", "postgres:16-alpine",
    )
    if r.returncode != 0:
        pytest.skip(f"Sin Docker para la prueba de respaldo: {r.stderr.strip()}")
    try:
        for _ in range(60):
            if _docker("exec", nombre, "pg_isready", "-h", "127.0.0.1", "-U", USUARIO).returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.skip("PostgreSQL de prueba no arrancó")
        puerto = _docker("port", nombre, "5432/tcp").stdout.split(":")[-1].strip()
        yield nombre, f"postgresql+asyncpg://{USUARIO}:t@127.0.0.1:{puerto}/{BASE}"
    finally:
        _docker("rm", "-f", nombre)


@pytest.fixture(scope="module")
def database_url(contenedor_pg):
    """Sustituye la fixture del conftest: `crear_app` usa la base del contenedor propio."""
    return contenedor_pg[1]


@pytest.fixture
def sesion(crear_app):
    """App con dos revisiones con veredicto (cadena de auditoría con registros)."""
    app = crear_app()
    match_id = app.configurar()
    for _ in range(2):
        resp = app.subir_clip(match_id)
        assert resp.status_code == 200, resp.text
        assert app.veredicto(resp.json()["revision_id"]).status_code == 200
    return app


@pytest.fixture
def entorno(contenedor_pg, sesion, tmp_path):
    """Variables del script. `datos` es la carpeta con storage/ y evidencia/ de la app."""
    respaldos = tmp_path / "respaldos"
    return {
        "PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""),
        "PG_CONTAINER": contenedor_pg[0], "POSTGRES_USER": USUARIO, "POSTGRES_DB_NAME": BASE,
        "DATOS_DIR": str(tmp_path), "RESPALDO_DIR": str(respaldos), "ENV_FILE": "/no/existe.env",
    }


def _correr(script: Path, entorno: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(script), *args], cwd=BACKEND, env=entorno, capture_output=True, text=True, check=False
    )


def _carpeta_respaldo(entorno: dict) -> Path:
    (carpeta,) = [p for p in Path(entorno["RESPALDO_DIR"]).iterdir() if p.is_dir()]
    return carpeta


def _nombre_base(carpeta: Path) -> str:
    """Nombre de los archivos del respaldo: sabre_<evento>_<fecha> (la carpeta es R<NNN>-<fecha>)."""
    return next(carpeta.glob("*.dump")).stem


def _conteos(sesion) -> str:
    fila = sesion.sql.filas(
        "SELECT (SELECT count(*) FROM sabre.revision_var) AS r, (SELECT count(*) FROM sabre.clasificacion) AS c, "
        "(SELECT count(*) FROM sabre.veredicto) AS v, (SELECT count(*) FROM sabre.registro_auditoria) AS a"
    )[0]
    return ",".join(str(fila[k]) for k in "rcva")


def test_respaldo_y_restauracion_coinciden(sesion, entorno):
    r = _correr(SCRIPT, entorno, "--evento", str(sesion.evento_id))

    assert r.returncode == 0, r.stdout + r.stderr
    print(r.stdout)  # visible con `pytest -s`: salida de un respaldo y su verificación
    carpeta = _carpeta_respaldo(entorno)
    fecha = carpeta.name.removeprefix("R001-")
    assert re.fullmatch(r"R001-\d{8}T\d{6}Z", carpeta.name)
    assert _nombre_base(carpeta) == f"sabre_{sesion.evento_id}_{fecha}"
    assert sorted(p.suffix or p.name for p in carpeta.iterdir()) == [".dump", ".sha256", ".tgz"]
    manifiesto = (carpeta / "MANIFEST.sha256").read_text()
    assert f"{_nombre_base(carpeta)}.dump" in manifiesto and f"{_nombre_base(carpeta)}.tgz" in manifiesto
    conteos = _conteos(sesion)
    assert int(conteos.split(",")[0]) >= 2 and int(conteos.split(",")[3]) > 0  # no es una base vacía
    assert f"conteos restaurados (revisiones,clasificaciones,veredictos,auditoría): {conteos}" in r.stdout
    assert "fn_verificar_auditoria(): 0 filas alteradas" in r.stdout
    # La base temporal de la verificación no queda
    bases = sesion.sql.filas("SELECT datname FROM pg_database WHERE datname LIKE 'sabre_verif%'")
    assert bases == []
    # Y el respaldo ya hecho se puede volver a verificar
    assert _correr(SCRIPT, entorno, "--verificar", str(carpeta)).returncode == 0


def test_dump_truncado_falla(sesion, entorno):
    assert _correr(SCRIPT, entorno, "--evento", str(sesion.evento_id)).returncode == 0
    carpeta = _carpeta_respaldo(entorno)
    dump = next(carpeta.glob("*.dump"))
    dump.write_bytes(dump.read_bytes()[: dump.stat().st_size * 6 // 10])

    # Con el MANIFEST original: los hashes ya no coinciden
    r = _correr(SCRIPT, entorno, "--verificar", str(carpeta))
    assert r.returncode != 0
    assert "hashes" in r.stderr

    # Con el MANIFEST rehecho a mano: el hash cuadra pero pg_restore no puede leer el dump
    lineas = subprocess.run(
        ["shasum", "-a", "256", dump.name, next(carpeta.glob("*.tgz")).name],
        cwd=carpeta, capture_output=True, text=True, check=True,
    ).stdout
    (carpeta / "MANIFEST.sha256").write_text(lineas)
    r = _correr(SCRIPT, entorno, "--verificar", str(carpeta))
    assert r.returncode != 0
    assert "pg_restore falló" in r.stderr
    assert sesion.sql.filas("SELECT datname FROM pg_database WHERE datname LIKE 'sabre_verif%'") == []


def test_sin_respaldo_dir_se_niega(sesion, entorno):
    del entorno["RESPALDO_DIR"]

    r = _correr(SCRIPT, entorno, "--evento", str(sesion.evento_id))

    assert r.returncode != 0
    assert "RESPALDO_DIR no está definida" in r.stderr


def test_respaldo_dir_dentro_del_repo_se_niega(sesion, entorno):
    entorno["RESPALDO_DIR"] = str(BACKEND / "datos" / "respaldo_prohibido")

    r = _correr(SCRIPT, entorno, "--evento", str(sesion.evento_id))

    assert r.returncode != 0
    assert "dentro de" in r.stderr
    assert not (BACKEND / "datos" / "respaldo_prohibido" / "x").exists()


def test_evento_inexistente_no_deja_respaldo(sesion, entorno):
    r = _correr(SCRIPT, entorno, "--evento", str(uuid.uuid4()))

    assert r.returncode != 0
    assert "no existe en la base" in r.stderr
    assert list(Path(entorno["RESPALDO_DIR"]).glob("R*")) == []


def test_los_respaldos_se_numeran_correlativamente(sesion, entorno):
    nombres = []
    for _ in range(3):
        assert _correr(SCRIPT, entorno, "--evento", str(sesion.evento_id)).returncode == 0
        time.sleep(1)  # la fecha lleva segundos
        nombres = sorted(p.name for p in Path(entorno["RESPALDO_DIR"]).iterdir() if p.is_dir())
    assert [n[:5] for n in nombres] == ["R001-", "R002-", "R003-"]
    # Un respaldo fallido conserva su número: el siguiente no lo reutiliza
    (Path(entorno["RESPALDO_DIR"]) / "R007-20261102T000000Z.FALLIDO").mkdir()
    assert _correr(SCRIPT, entorno, "--evento", str(sesion.evento_id)).returncode == 0
    assert any(p.name.startswith("R008-") for p in Path(entorno["RESPALDO_DIR"]).iterdir())


def test_recordatorio_avisa_hasta_que_se_respalda(sesion, entorno):
    sin_dir = {k: v for k, v in entorno.items() if k != "RESPALDO_DIR"}
    r = _correr(RECORDAR, sin_dir)
    assert r.returncode == 0 and "SIN RESPALDO" in r.stderr

    # La base del módulo acumula las revisiones de las pruebas anteriores: se cuentan, no se fijan.
    total = int(sesion.sql.escalar("SELECT count(*) FROM sabre.revision_var"))
    r = _correr(RECORDAR, entorno)
    assert r.returncode == 0 and f"FALTA RESPALDAR: {total} revisiones nuevas" in r.stderr

    assert _correr(SCRIPT, entorno, "--evento", str(sesion.evento_id)).returncode == 0
    assert f"Respaldo al día ({total} revisiones" in _correr(RECORDAR, entorno).stdout

    resp = sesion.subir_clip(sesion.sql.escalar("SELECT id FROM sabre.combate LIMIT 1").__str__())
    assert resp.status_code == 200, resp.text
    r = _correr(RECORDAR, entorno)
    assert "FALTA RESPALDAR: 1 revisiones nuevas" in r.stderr


def test_exportar_evidencia_sin_respaldo_dir_avisa_y_sale_con_2(sesion, tmp_path, monkeypatch, capsys):
    from scripts import exportar_evidencia
    from shared import config

    monkeypatch.setattr(config, "DATABASE_URL", sesion.sql._url)
    monkeypatch.setattr(config, "EVIDENCE_DIR", str(tmp_path / "evidencia_export"))
    monkeypatch.delenv("RESPALDO_DIR", raising=False)
    monkeypatch.setenv("ENV_FILE", "/no/existe.env")

    codigo = exportar_evidencia.main(["--evento", str(sesion.evento_id)])

    assert codigo == 2
    assert "SIN RESPALDO" in capsys.readouterr().err
    assert (tmp_path / "evidencia_export" / str(sesion.evento_id) / "resumen.json").is_file()


def test_exportar_evidencia_llama_al_respaldo(sesion, entorno, monkeypatch):
    from scripts import exportar_evidencia
    from shared import config

    monkeypatch.setattr(config, "DATABASE_URL", sesion.sql._url)
    monkeypatch.setattr(config, "EVIDENCE_DIR", str(sesion.evidencia_dir))
    for k, v in entorno.items():
        monkeypatch.setenv(k, v)

    codigo = exportar_evidencia.main(["--evento", str(sesion.evento_id)])

    assert codigo == 0
    carpeta = _carpeta_respaldo(entorno)
    assert carpeta.name.startswith("R001-")
    assert next(carpeta.glob("*.dump")).stat().st_size > 0
