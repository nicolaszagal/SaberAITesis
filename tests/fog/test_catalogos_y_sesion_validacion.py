"""GET /eventos, GET /usuarios?rol= (solo lectura) y
scripts/crear_sesion_validacion.py (idempotente por nombre), contra
PostgreSQL real (ver conftest.py)."""

from __future__ import annotations

import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

from alembic import command

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "crear_sesion_validacion.py"


def _nombre(prefijo: str) -> str:
    return f"{prefijo}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# GET /eventos
# ---------------------------------------------------------------------------

def test_get_eventos_lista_los_eventos_del_mas_reciente_al_mas_antiguo(crear_app):
    app = crear_app()
    viejo, nuevo = _nombre("Viejo"), _nombre("Nuevo")
    app.sql.ejecutar(
        "INSERT INTO sabre.evento (nombre, fecha, lugar, tipo) VALUES "
        "(:v, '2031-01-01', NULL, 'formativo'), (:n, '2031-06-15', 'Lima', 'piloto')",
        v=viejo, n=nuevo,
    )

    resp = app.client.get("/eventos")

    assert resp.status_code == 200
    eventos = resp.json()
    nombres = [e["nombre"] for e in eventos]
    assert nombres.index(nuevo) < nombres.index(viejo)
    por_nombre = {e["nombre"]: e for e in eventos}
    assert por_nombre[nuevo]["fecha"] == "2031-06-15"
    assert por_nombre[nuevo]["lugar"] == "Lima"
    assert por_nombre[nuevo]["tipo"] == "piloto"
    assert por_nombre[viejo]["lugar"] is None
    assert set(por_nombre[nuevo]) == {"id", "nombre", "fecha", "lugar", "tipo"}
    # El id sirve como evento_id de POST /matches/config
    assert app.client.post(
        "/matches/config", json=app.body_config(evento_id=por_nombre[nuevo]["id"])
    ).status_code == 200


def test_eventos_es_de_solo_lectura(crear_app):
    app = crear_app()
    antes = app.sql.escalar("SELECT count(*) FROM sabre.evento")

    respuestas = [
        app.client.post("/eventos", json={"nombre": "x", "fecha": "2031-01-01", "tipo": "piloto"}),
        app.client.put(f"/eventos/{uuid.uuid4()}", json={}),
        app.client.delete(f"/eventos/{uuid.uuid4()}"),
    ]

    assert all(r.status_code in (404, 405) for r in respuestas)
    assert app.sql.escalar("SELECT count(*) FROM sabre.evento") == antes


# ---------------------------------------------------------------------------
# GET /usuarios
# ---------------------------------------------------------------------------

def test_get_usuarios_filtra_por_rol(crear_app):
    app = crear_app()
    arbitro, operador = _nombre("Arbitro"), _nombre("Operador")
    app.sql.ejecutar(
        "INSERT INTO sabre.usuario (nombre, rol, activo) VALUES "
        "(:a, 'arbitro', TRUE), (:o, 'operador', FALSE)", a=arbitro, o=operador,
    )

    arbitros = app.client.get("/usuarios", params={"rol": "arbitro"})
    operadores = app.client.get("/usuarios", params={"rol": "operador"})
    todos = app.client.get("/usuarios")

    assert arbitros.status_code == operadores.status_code == todos.status_code == 200
    assert {u["rol"] for u in arbitros.json()} == {"arbitro"}
    assert arbitro in [u["nombre"] for u in arbitros.json()]
    assert operador not in [u["nombre"] for u in arbitros.json()]
    fila_operador = next(u for u in operadores.json() if u["nombre"] == operador)
    assert fila_operador["activo"] is False
    assert set(fila_operador) == {"id", "nombre", "rol", "activo"}
    nombres_todos = [u["nombre"] for u in todos.json()]
    assert arbitro in nombres_todos and operador in nombres_todos
    assert nombres_todos == sorted(nombres_todos)  # ordenados por nombre


def test_get_usuarios_con_rol_invalido_responde_422(crear_app):
    app = crear_app()

    assert app.client.get("/usuarios", params={"rol": "atleta"}).status_code == 422


def test_usuarios_es_de_solo_lectura(crear_app):
    app = crear_app()
    antes = app.sql.escalar("SELECT count(*) FROM sabre.usuario")

    respuestas = [
        app.client.post("/usuarios", json={"nombre": "x", "rol": "arbitro"}),
        app.client.delete(f"/usuarios/{uuid.uuid4()}"),
    ]

    assert all(r.status_code in (404, 405) for r in respuestas)
    assert app.sql.escalar("SELECT count(*) FROM sabre.usuario") == antes


def test_el_arbitro_listado_sirve_para_configurar_un_combate(crear_app):
    app = crear_app()
    arbitro = app.client.get("/usuarios", params={"rol": "arbitro"}).json()[0]

    resp = app.client.post("/matches/config", json=app.body_config(arbitro_id=arbitro["id"]))

    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# scripts/crear_sesion_validacion.py
# ---------------------------------------------------------------------------

def _correr_script(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": "", "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60,
    )


def _ids(salida: str) -> dict[str, str]:
    ids = {}
    for linea in salida.splitlines():
        clave, _, resto = linea.partition(": ")
        if clave in ("evento_id", "arbitro_id", "operador_id"):
            ids[clave] = resto.split()[0]
    return ids


def test_script_crea_evento_piloto_arbitro_y_operador(database_url, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    evento, arbitro, operador = _nombre("Piloto"), _nombre("Arb"), _nombre("Op")

    r = _correr_script(
        database_url, "--evento", evento, "--fecha", "2026-10-05",
        "--arbitro", arbitro, "--operador", operador,
    )

    assert r.returncode == 0, r.stderr
    ids = _ids(r.stdout)
    assert set(ids) == {"evento_id", "arbitro_id", "operador_id"}
    assert r.stdout.count("(creado)") == 3
    from tests.fog.conftest import SQL

    sql = SQL(database_url)
    fila = sql.filas("SELECT * FROM sabre.evento WHERE id = :i", i=ids["evento_id"])[0]
    assert (fila["nombre"], fila["tipo"], fila["fecha"]) == (evento, "piloto", date(2026, 10, 5))
    usuarios = {
        str(u["id"]): (u["nombre"], u["rol"], u["activo"])
        for u in sql.filas(
            "SELECT * FROM sabre.usuario WHERE id IN (:a, :o)",
            a=ids["arbitro_id"], o=ids["operador_id"],
        )
    }
    assert usuarios[ids["arbitro_id"]] == (arbitro, "arbitro", True)
    assert usuarios[ids["operador_id"]] == (operador, "operador", True)


def test_script_es_idempotente_por_nombre(database_url, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    evento, arbitro, operador = _nombre("Piloto"), _nombre("Arb"), _nombre("Op")
    args = ("--evento", evento, "--fecha", "2026-10-05", "--arbitro", arbitro, "--operador", operador)
    from tests.fog.conftest import SQL

    sql = SQL(database_url)

    primera = _correr_script(database_url, *args)
    segunda = _correr_script(database_url, *args)

    assert primera.returncode == segunda.returncode == 0, segunda.stderr
    assert _ids(primera.stdout) == _ids(segunda.stdout)
    assert segunda.stdout.count("(ya existía)") == 3
    assert sql.escalar("SELECT count(*) FROM sabre.evento WHERE nombre = :n", n=evento) == 1
    assert sql.escalar(
        "SELECT count(*) FROM sabre.usuario WHERE nombre IN (:a, :o)", a=arbitro, o=operador
    ) == 2


def test_script_completa_solo_lo_que_falta_y_no_cambia_la_fecha(database_url, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    evento, arbitro = _nombre("Piloto"), _nombre("Arb")
    primero = _correr_script(
        database_url, "--evento", evento, "--fecha", "2026-10-05",
        "--arbitro", arbitro, "--operador", "Op Uno",
    )

    segundo = _correr_script(
        database_url, "--evento", evento, "--fecha", "2026-11-01",
        "--arbitro", arbitro, "--operador", "Op Dos",
    )

    assert primero.returncode == segundo.returncode == 0, segundo.stderr
    ids_1, ids_2 = _ids(primero.stdout), _ids(segundo.stdout)
    assert ids_1["evento_id"] == ids_2["evento_id"]
    assert ids_1["arbitro_id"] == ids_2["arbitro_id"]
    assert ids_1["operador_id"] != ids_2["operador_id"]  # otro operador: se crea
    assert "AVISO" in segundo.stderr and "2026-10-05" in segundo.stderr


def test_script_rechaza_un_evento_existente_que_no_es_piloto(database_url, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    from tests.fog.conftest import SQL

    sql = SQL(database_url)
    oficial = _nombre("Oficial")
    sql.ejecutar("INSERT INTO sabre.evento (nombre, fecha, tipo) VALUES (:n, '2026-01-01', 'oficial')", n=oficial)
    arbitro = _nombre("Arb")

    r = _correr_script(
        database_url, "--evento", oficial, "--fecha", "2026-10-05",
        "--arbitro", arbitro, "--operador", "Op",
    )

    assert r.returncode == 1
    assert "oficial" in r.stderr
    assert sql.escalar("SELECT count(*) FROM sabre.usuario WHERE nombre = :a", a=arbitro) == 0  # atómico


def test_script_valida_los_argumentos(database_url):
    r = _correr_script(
        database_url, "--evento", "X", "--fecha", "05/10/2026", "--arbitro", "A", "--operador", "O"
    )
    assert r.returncode == 2 and "YYYY-MM-DD" in r.stderr

    r = _correr_script(database_url, "--evento", "X", "--fecha", "2026-10-05", "--arbitro", "A")
    assert r.returncode == 2 and "--operador" in r.stderr
